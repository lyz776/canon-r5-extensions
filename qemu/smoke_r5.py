"""Run synthetic ARM code in QEMU-EOS R5; contains no Canon firmware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile


MARKER = b"SYNTHETIC R5 CPU/RAM OK\n"


def program(case):
    # ARM state at the model's 0xE0000000 reset PC. All addresses refer to
    # synthetic memory. SVC 0x123456 invokes QEMU semihosting, not camera APIs.
    words = [
        0xE59F2034,  # 00 ldr r2,[pc,#52] -> RAM address at 60
        0xE3A0305A,  # 04 mov r3,#0x5a
        0xE5823000,  # 08 str r3,[r2]
        0xE5924000,  # 12 ldr r4,[r2]
        0xE354005B if case == "wrong_value" else 0xE354005A,  # 16 cmp r4,#value
        0x1A000005,  # 20 bne 48 (failure exit)
        0xE3A00004,  # 24 mov r0,#SYS_WRITE0
        0xE28F1020,  # 28 adr r1,message at 68
        0xEF123456,  # 32 svc semihosting
        0xEAFFFFFE if case == "loop" else 0xE3A00018,  # 36 loop / SYS_EXIT
        0xE59F1010,  # 40 ldr r1,[pc,#16] -> exit reason at 64
        0xEF123456,  # 44 svc semihosting
        0xE3A00018,  # 48 mov r0,#SYS_EXIT
        0xE3A01001,  # 52 mov r1,#1 (abnormal termination)
        0xEF123456,  # 56 svc semihosting
        0x00010000,  # 60 scratch word in the model's RAM
        0x00020026,  # 64 ADP_Stopped_ApplicationExit
    ]
    return struct.pack("<17I", *words) + MARKER + b"\0"


def fingerprint(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run_case(qemu, root, case, payload=None, log_mode=None, expected_trace=None):
    directory = root / case
    roms = directory / "R5"
    roms.mkdir(parents=True)
    for name, header in (("ROM0.BIN", program(case) if payload is None else payload),
                         ("ROM1.BIN", b"SYNTHETIC DATA ONLY; NO CANON FIRMWARE\0")):
        with (roms / name).open("xb") as stream:
            stream.write(header)
            stream.truncate(64 * 1024 * 1024)
    for name in ("sd.img", "cf.img"):
        with (directory / name).open("xb") as stream:
            stream.truncate(16 * 1024 * 1024)
    inputs = sorted(path for path in directory.rglob("*") if path.is_file())
    before = {path: fingerprint(path) for path in inputs}
    command = [
        str(qemu), "-M", "R5", "-smp", "2", "-nodefaults", "-no-user-config",
        "-display", "none", "-monitor", "none", "-serial", "none",
        "-net", "none", "-no-reboot", "-snapshot", "-semihosting",
        "-drive", "file=sd.img,if=sd,format=raw",
        "-drive", "file=cf.img,if=ide,format=raw",
    ]
    if log_mode:
        command += ["-d", log_mode]
    # Do not inherit EOS paths/debug hooks from unrelated research sessions.
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("QEMU_EOS_", "QEMU_ML_"))}
    env["QEMU_EOS_WORKDIR"] = str(directory)
    timed_out = False
    try:
        result = subprocess.run(command, cwd=directory, capture_output=True,
                                env=env,
                                timeout=5 if case == "loop" else 20)
        output = result.stdout + result.stderr
        returncode = result.returncode
    except subprocess.TimeoutExpired as error:
        # subprocess.run kills and waits for its own child on timeout.
        timed_out = True
        output = (error.stdout or b"") + (error.stderr or b"")
        returncode = None
    preserved = before == {path: fingerprint(path) for path in inputs}
    # MinGW's stderr text mode expands LF to CRLF.
    reached_marker = MARKER in output.replace(b"\r\n", b"\n")
    if case == "wrong_value":
        passed = not timed_out and returncode == 1 and not reached_marker
    elif case == "loop":
        passed = timed_out and reached_marker
    else:
        passed = not timed_out and returncode == 0 and reached_marker
    trace = []
    for line in output.splitlines():
        match = re.search(rb"\[0x([0-9A-F]+)\] (->|<-) 0x([0-9A-F]+)", line)
        if match:
            width = 1 if b"8-bit" in line else 2 if b"16-bit" in line else 4
            trace.append((int(match[1], 16), match[2].decode(), int(match[3], 16), width))
    if expected_trace is not None:
        passed = passed and trace == expected_trace
    return {
        "case": case, "test_passed": passed and preserved,
        "emulator_exit_code": returncode, "timed_out": timed_out,
        "reached_marker": reached_marker, "input_bytes_preserved": preserved,
        "expected_trace": expected_trace, "actual_trace": trace,
        "emulator_output": output.decode("utf-8", errors="replace").replace(str(directory), "<temporary-dir>"),
    }


def memory_tests(qemu, root, prefix, alignment_probe=False):
    # Expected accesses are independent of QEMU's implementation and include
    # order/count, so missing, duplicate or wrongly sized records fail.
    accesses = [
        (0x10000, "<-", 0xA5, 1), (0x10000, "->", 0xA5, 1),
        (0x10002, "<-", 0x8001, 2), (0x10002, "->", 0x8001, 2),
        (0x10002, "->", 0x8001, 2),
        (0x10004, "<-", 0x12345678, 4), (0x10004, "->", 0x12345678, 4),
        (0x10008, "<-", 0x12345678, 4), (0x10008, "->", 0x12345678, 4),
        (0x10004, "->", 0x12345678, 4),
        (0x10010, "<-", 0x11, 4), (0x10014, "<-", 0x22, 4),
        (0x10010, "->", 0x11, 4), (0x10014, "->", 0x22, 4),
    ]
    source = Path(__file__).with_name("memory_log.S").resolve()
    results = []
    for mode, isa in enumerate(("arm", "thumb16", "thumb32")):
        for fault in ((0, 1, 2, 3, 4) if alignment_probe else (0, 1, 2)):
            stem = root / f"{isa}-{fault}"
            commands = [
                [prefix + "as", "-mcpu=cortex-a9", "--defsym", f"MODE={mode}",
                 "--defsym", f"FAULT={fault}", "-o", str(stem.with_suffix(".o")), str(source)],
                [prefix + "ld", "-Ttext=0xe0000000", "-e", "_start", "-o",
                 str(stem.with_suffix(".elf")), str(stem.with_suffix(".o"))],
                [prefix + "objcopy", "-O", "binary", str(stem.with_suffix(".elf")),
                 str(stem.with_suffix(".bin"))],
            ]
            for command in commands:
                subprocess.run(command, check=True, timeout=30)
            payload = stem.with_suffix(".bin").read_bytes()
            for log_mode in ((None, "ramr", "ramw", "ram") if not fault else ("ram",)):
                expected = [] if fault else [a for a in accesses if
                    log_mode == "ram" or (log_mode == "ramr" and a[1] == "->") or
                    (log_mode == "ramw" and a[1] == "<-")]
                if fault in (1, 2):
                    expected = [(0x7800, "<-", 0xE0000C02, 4)]
                name = f"{isa}-fault{fault}-{log_mode or 'no-log'}"
                results.append(run_case(qemu, root, name, payload, log_mode, expected))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("qemu", type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--probe-memory-log", action="store_true",
                        help="check ARM/Thumb RAM traces and MMU faults; requires ARM binutils")
    parser.add_argument("--probe-alignment", action="store_true",
                        help="also require SCTLR.A alignment faults (known upstream gap)")
    parser.add_argument("--binutils-prefix", default="arm-none-eabi-",
                        help="tool prefix, optionally including an absolute directory")
    args = parser.parse_args()
    qemu = args.qemu.resolve(strict=True)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    cases = ("pass", "wrong_value", "loop")
    with tempfile.TemporaryDirectory(prefix="synthetic-r5-", dir=args.work_dir) as folder:
        results = [run_case(qemu, Path(folder).resolve(), case)
                   for case in cases]
        if args.probe_memory_log or args.probe_alignment:
            results += memory_tests(qemu, Path(folder).resolve(), args.binutils_prefix,
                                    args.probe_alignment)
    print(json.dumps({"scope": "synthetic ARM CPU/RAM only; no Canon firmware or hardware tested",
                      "results": results}, indent=2))
    return 0 if all(item["test_passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
