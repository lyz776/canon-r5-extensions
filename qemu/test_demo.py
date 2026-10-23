"""Integration checks: python -B qemu/test_demo.py path/to/qemu-system-arm.exe"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from demo import BASE, Session


QEMU = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else None


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qemu-demo-test-")
        self.work = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def session(self):
        session = Session(QEMU, self.work)
        self.addCleanup(session.close)
        return session

    def wait_breakpoint(self, session):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if session.poll():
                return
            time.sleep(0.01)
        self.fail("QEMU did not stop at the breakpoint")

    def test_steps_and_60_run_pause_cycles(self):
        session = self.session()
        regs, ram = session.snapshot()
        self.assertEqual((regs[15], regs[0], ram), (BASE, 0, 0))
        for expected in [(BASE + 4, 0, 0), (BASE + 8, 0, 0),
                         (BASE + 12, 1, 0), (BASE + 16, 1, 1)]:
            regs, ram = session.step()
            self.assertEqual((regs[15], regs[0], ram), expected)
        self.assertEqual(regs[1], 0x10000)
        for _ in range(60):
            session.run(breakpoint=True)
            self.wait_breakpoint(session)
            regs, ram = session.snapshot()
            self.assertEqual((regs[15], regs[0]), (BASE + 12, ram + 1))
            regs, ram = session.step()
            self.assertEqual((regs[15], regs[0]), (BASE + 16, ram))
            previous = ram
            session.run()
            with self.assertRaises(RuntimeError):
                session.snapshot()
            time.sleep(0.01)
            regs, ram = session.pause()
            self.assertGreater(ram, previous)
            self.assertIn(regs[15], (BASE + 8, BASE + 12, BASE + 16))
            self.assertIn(regs[0] - ram, (0, 1))
        process, folder = session.process, Path(session.temp.name)
        self.assertTrue(session.close(), "Input image bytes changed")
        self.assertIsNotNone(process.poll())
        self.assertFalse(folder.exists())
        self.assertTrue(session.close(), "Close must be idempotent")
        restarted = self.session()
        regs, ram = restarted.snapshot()
        self.assertEqual((regs[15], regs[0], ram), (BASE, 0, 0))
        self.assertTrue(restarted.close())

    def test_missing_executable_leaves_no_files(self):
        with self.assertRaises(FileNotFoundError):
            Session(self.work / "missing.exe", self.work)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_startup_failure_cleans_files(self):
        # Existing non-executable file exercises failure after image creation.
        invalid = self.work / "invalid.exe"
        invalid.write_bytes(b"not an executable")
        with self.assertRaises(OSError):
            Session(invalid, self.work)
        self.assertEqual(list(self.work.iterdir()), [invalid])

    def test_qemu_exit_detected_and_cleaned(self):
        session = self.session()
        session.run()
        process = session.process
        process.terminate()
        process.wait(timeout=3)
        deadline = time.monotonic() + 3
        with self.assertRaises((RuntimeError, OSError)):
            while time.monotonic() < deadline:
                session.poll()
                time.sleep(0.01)
            self.fail("Disconnected debugger was not detected")
        self.assertTrue(session.close())
        self.assertEqual(list(self.work.iterdir()), [])

    def test_bad_protocol_checksum_rejected(self):
        client, peer = socket.socketpair()
        self.addCleanup(client.close)
        self.addCleanup(peer.close)
        session = Session.__new__(Session)
        session.sock, session.buffer = client, b""
        client.settimeout(1)
        peer.sendall(b"$T05#00")
        with self.assertRaisesRegex(RuntimeError, "校验失败"):
            session.receive()
        with self.assertRaises(RuntimeError):
            Session.stop_reply("Tgarbage")

    @unittest.skipUnless(os.name == "nt", "Windows Job Object behavior")
    def test_abrupt_parent_exit_terminates_qemu(self):
        child = subprocess.Popen(
            [sys.executable, "-B", str(Path(__file__).resolve()),
             str(QEMU), "--job-child", str(self.work)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        # Save a process handle before killing its parent, avoiding PID reuse.
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as reader:
                future = reader.submit(child.stdout.readline)
                try:
                    line = future.result(timeout=12)
                except Exception:
                    child.kill()
                    raise
            self.assertTrue(line.strip().isdigit(), line)
            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            api.OpenProcess.restype = wintypes.HANDLE
            api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = api.OpenProcess(0x100000, False, int(line))
            self.assertTrue(handle)
            try:
                child.kill()  # No Python finally/atexit runs in the child.
                child.wait(timeout=3)
                self.assertEqual(api.WaitForSingleObject(handle, 3000), 0,
                                 "QEMU survived its GUI parent's termination")
            finally:
                api.CloseHandle(handle)
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=3)
        # Abrupt death may leave synthetic files, cleaned by this test's tempdir.


if __name__ == "__main__":
    if QEMU is None:
        raise SystemExit(__doc__)
    if len(sys.argv) > 1 and sys.argv[1] == "--job-child":
        child_session = Session(QEMU, Path(sys.argv[2]))
        print(child_session.process.pid, flush=True)
        time.sleep(60)
        child_session.close()
    else:
        unittest.main(verbosity=2)
