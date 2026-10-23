"""Small interactive QEMU-EOS demonstration. Only the built-in synthetic ROM is loaded."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import select
import socket
import struct
import subprocess
import tempfile
import time
import tkinter as tk
from tkinter import ttk


BASE = 0xE0000000
ROWS = [
    (0xE3A01801, "mov r1, #0x10000", "选择虚拟 RAM 地址"),
    (0xE3A00000, "mov r0, #0", "计数器清零"),
    (0xE2800001, "add r0, r0, #1", "计数器加一"),
    (0xE5810000, "str r0, [r1]", "把计数器写入虚拟 RAM"),
    (0xEAFFFFFC, "b 0xE0000008", "回到加一，继续循环"),
]


def child_job(process):
    """Windows closes this job on parent death, terminating its QEMU child."""
    if os.name != "nt":
        return None
    class Basic(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t),
                    ("max_ws", ctypes.c_size_t), ("active", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD)]
    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", ctypes.c_uint64 * 6),
                    ("limits", ctypes.c_size_t * 4)]
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    api.CreateJobObjectW.restype = wintypes.HANDLE
    api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    job = api.CreateJobObjectW(None, None)
    info = Extended()
    info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    if not api.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) or not api.AssignProcessToJobObject(job, int(process._handle)):
        error = ctypes.WinError(ctypes.get_last_error())
        api.CloseHandle(job)
        raise error
    return api, job


class Session:
    def __init__(self, qemu, work):
        self.process = self.sock = self.job = self.log = self.temp = None
        self.running = False
        self.breakpoint = False
        self.buffer = b""
        self.ack = False
        self.next_send = 0.0
        self.inputs = {}
        try:
            if not qemu.is_file():
                raise FileNotFoundError(f"找不到 QEMU：{qemu}")
            work.mkdir(parents=True, exist_ok=True)
            self.temp = tempfile.TemporaryDirectory(prefix="qemu-demo-", dir=work)
            folder = Path(self.temp.name).resolve()
            (folder / "R5").mkdir()
            payload = struct.pack("<5I", *(row[0] for row in ROWS))
            for name, data, size in [("R5/ROM0.BIN", payload, 64 << 20),
                                     ("R5/ROM1.BIN", b"SYNTHETIC ONLY", 64 << 20),
                                     ("sd.img", b"", 16 << 20), ("cf.img", b"", 16 << 20)]:
                path = folder / name
                with path.open("xb") as stream:
                    stream.write(data)
                    stream.truncate(size)
                self.inputs[path] = self.digest(path)
            self.log = (folder / "qemu.log").open("w+b")
            # Python listens first; QEMU connects as a client. No port-selection race
            # and no QEMU debugger listener remains open after this handshake.
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                listener.settimeout(8)
                port = listener.getsockname()[1]
                command = [str(qemu), "-M", "R5", "-smp", "2", "-accel", "tcg,thread=single", "-S", "-nodefaults",
                           "-no-user-config", "-display", "none", "-monitor", "none",
                           "-serial", "none", "-net", "none", "-no-reboot", "-snapshot",
                           "-drive", "file=sd.img,if=sd,format=raw",
                           "-drive", "file=cf.img,if=ide,format=raw",
                           "-chardev", f"socket,id=debug,host=127.0.0.1,port={port},delay=off",
                           "-gdb", "chardev:debug"]
                env = {k: v for k, v in os.environ.items()
                       if not k.upper().startswith(("QEMU_EOS_", "QEMU_ML_"))}
                env["QEMU_EOS_WORKDIR"] = str(folder)
                self.process = subprocess.Popen(command, cwd=folder, env=env,
                                                stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,
                                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                self.job = child_job(self.process)
                self.sock, _ = listener.accept()
            self.sock.settimeout(2)
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.stop_reply(self.request("?"))
            for command in ("Hg1", "Hc1"):
                self.ok(self.request(command))
            # The table above is a listing of our own fixture, not a disassembler.
            if self.request(f"m{BASE:x},14") != payload.hex():
                raise RuntimeError("QEMU 内的程序与演示源码不一致")
        except Exception:
            self.close()
            raise

    @staticmethod
    def digest(path):
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    @staticmethod
    def ok(reply):
        if reply != "OK":
            raise RuntimeError(f"QEMU 拒绝请求：{reply}")

    @staticmethod
    def stop_reply(reply):
        if len(reply) < 3 or reply[0] not in "TS" or reply[1:3] not in ("02", "05"):
            raise RuntimeError(f"未收到暂停确认：{reply}")

    def send(self, command):
        # Burst requests timed out intermittently in this Windows build. A 10 ms
        # gap passed our stress test; the underlying cause is not established.
        # Never retry a step/continue blindly.
        time.sleep(max(0, self.next_send - time.monotonic()))
        data = command.encode("ascii")
        packet = b"$" + data + b"#" + f"{sum(data) & 255:02x}".encode()
        self.sock.sendall((b"+" if self.ack else b"") + packet)
        self.ack = False

    def receive(self):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.buffer = self.buffer.lstrip(b"+")
            if self.buffer.startswith(b"-"):
                raise RuntimeError("调试协议校验被 QEMU 拒绝")
            end = self.buffer.find(b"#")
            if self.buffer.startswith(b"$") and end >= 0 and len(self.buffer) >= end + 3:
                data = self.buffer[1:end]
                check = int(self.buffer[end + 1:end + 3], 16)
                self.buffer = self.buffer[end + 3:]
                if sum(data) & 255 != check:
                    raise RuntimeError("调试响应校验失败")
                self.ack = True
                self.next_send = time.monotonic() + 0.01
                return data.decode("ascii")
            data = self.sock.recv(8192)
            if not data or len(self.buffer) + len(data) > 65536:
                raise RuntimeError("QEMU 调试连接已关闭或响应过大")
            self.buffer += data
        raise TimeoutError("QEMU 调试响应超时")

    def request(self, command):
        self.send(command)
        return self.receive()

    def snapshot(self):
        if self.running:
            raise RuntimeError("请先暂停，再读取寄存器")
        regs = struct.unpack("<16I", bytes.fromhex(self.request("g"))[:64])
        memory = int.from_bytes(bytes.fromhex(self.request("m10000,4")), "little")
        return regs, memory

    def step(self):
        if self.running:
            raise RuntimeError("请先暂停")
        if self.breakpoint:
            self.ok(self.request("z0,e000000c,4"))
            self.breakpoint = False
        self.stop_reply(self.request("s"))
        return self.snapshot()

    def run(self, breakpoint=False):
        if self.running:
            raise RuntimeError("程序已经在运行")
        if self.breakpoint:
            self.ok(self.request("z0,e000000c,4"))
            self.breakpoint = False
        # If currently on the breakpoint, first execute that instruction once.
        if breakpoint and self.snapshot()[0][15] == BASE + 12:
            self.step()
        if breakpoint:
            self.ok(self.request("Z0,e000000c,4"))
            self.breakpoint = True
        self.send("c")
        self.running = True

    def poll(self):
        self.buffer = self.buffer.lstrip(b"+")
        if self.running and (self.buffer or select.select([self.sock], [], [], 0)[0]):
            # An ACK alone is not a stop packet; retain it until more data arrives.
            if not self.buffer:
                data = self.sock.recv(8192)
                if not data:
                    raise RuntimeError("QEMU 调试连接已关闭")
                self.buffer = data.lstrip(b"+")
            if self.buffer:
                self.stop_reply(self.receive())
                self.running = False
                return True
        return False

    def pause(self):
        if self.running:
            self.sock.sendall(b"\x03")
            self.stop_reply(self.receive())
            self.running = False
        return self.snapshot()

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        if self.sock:
            self.sock.close()
            self.sock = None
        if self.job:
            api, job = self.job
            api.CloseHandle(job)
            self.job = None
        if self.log:
            self.log.close()
            self.log = None
        preserved = all(path.exists() and self.digest(path) == digest for path, digest in self.inputs.items())
        if self.temp:
            self.temp.cleanup()
        self.process = self.sock = self.job = self.log = self.temp = None
        self.inputs = {}
        self.running = False
        return preserved


class Demo:
    def __init__(self, root, qemu, work):
        self.root, self.qemu, self.work = root, qemu, work
        self.session = None
        self.started = 0
        root.title("QEMU-EOS · 可操作演示（合成程序）")
        root.geometry("1020x720")
        root.minsize(950, 650)
        root.configure(bg="#f4f5f7")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TButton", font=("Microsoft YaHei UI", 11), padding=8)
        style.configure("Treeview", rowheight=32, font=("Consolas", 11))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10))
        body = ttk.Frame(root, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="亲自控制 QEMU 中的程序", font=("Microsoft YaHei UI", 22, "bold")).pack(anchor="w")
        ttk.Label(body, text="真实 QEMU-EOS · R5 模型 · 自写 ARM 计数器 · 尚未加载佳能固件或相机菜单",
                  font=("Microsoft YaHei UI", 10), foreground="#755411").pack(anchor="w", pady=(6, 15))
        bar = ttk.Frame(body)
        bar.pack(fill="x")
        self.buttons = {}
        for name, action in [("启动 / 重新开始", self.restart), ("单步", self.step),
                             ("运行至写入断点", lambda: self.run(True)),
                             ("连续运行", lambda: self.run(False)), ("暂停", self.pause), ("停止 QEMU", self.stop)]:
            button = ttk.Button(bar, text=name, command=lambda f=action: self.guard(f))
            button.pack(side="left", padx=(0, 6))
            self.buttons[name] = button
        self.status = tk.StringVar(value="未启动。点“启动 / 重新开始”，QEMU 将停在第一条指令。")
        ttk.Label(body, textvariable=self.status, font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=12)
        self.code = ttk.Treeview(body, columns=("addr", "asm", "meaning"), show="headings", height=5, selectmode="none")
        for column, label, width in [("addr", "下一条指令地址", 145), ("asm", "合成程序指令", 260), ("meaning", "这条指令做什么", 400)]:
            self.code.heading(column, text=label)
            self.code.column(column, width=width)
        for i, (_, asm, meaning) in enumerate(ROWS):
            self.code.insert("", "end", iid=str(BASE + i * 4), values=(f"0x{BASE+i*4:08X}", asm, meaning))
        self.code.tag_configure("pc", background="#d8ece8", foreground="#145147")
        self.code.pack(fill="x")
        self.values = tk.StringVar(value="R0  —          R1  —          PC  —\n虚拟 RAM [0x00010000]  —")
        ttk.Label(body, textvariable=self.values, font=("Consolas", 15), padding=(0, 14)).pack(anchor="w")
        ttk.Label(body, text="验收：单步 3 次，R0 应为 1、RAM 仍为 0；再单步 1 次，RAM 变为 1。\n"
                  "断点停在写入之前；连续运行时数值是上次暂停的快照，暂停后更新。连续运行最多 10 秒。",
                  font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(0, 10))
        self.history = tk.Text(body, height=7, font=("Microsoft YaHei UI", 10), state="disabled", relief="flat", bg="#e9edf0")
        self.history.pack(fill="both", expand=True)
        ttk.Label(body, text="仅操作电脑内的临时虚拟内存和镜像。关闭窗口会终止本窗口启动的 QEMU；不连接相机。",
                  font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(10, 0))
        self.controls()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.tick)

    def note(self, text):
        self.history.configure(state="normal")
        self.history.insert("end", time.strftime("%H:%M:%S ") + text + "\n")
        if int(self.history.index("end-1c").split(".")[0]) > 100:
            self.history.delete("1.0", "2.0")
        self.history.see("end")
        self.history.configure(state="disabled")

    def controls(self):
        active = self.session is not None
        running = active and self.session.running
        for name, button in self.buttons.items():
            enabled = name == "启动 / 重新开始" or (active and (name == "停止 QEMU" or (running if name == "暂停" else not running)))
            button.configure(state="normal" if enabled else "disabled")

    def show(self, snapshot, reason):
        regs, memory = snapshot
        for row in self.code.get_children():
            self.code.item(row, tags=("pc",) if int(row) == regs[15] else ())
        self.values.set(f"R0  {regs[0]:10d}     R1  0x{regs[1]:08X}     PC  0x{regs[15]:08X}\n"
                        f"虚拟 RAM [0x00010000]  {memory}  (0x{memory:08X})")
        self.status.set("已暂停 · " + reason)
        self.note(f"{reason}  PC=0x{regs[15]:08X}  R0={regs[0]}  RAM={memory}")
        self.controls()

    def restart(self):
        self.stop()
        self.session = Session(self.qemu, self.work)
        self.show(self.session.snapshot(), "已启动；绿色行是下一条将执行的指令")

    def step(self):
        self.show(self.session.step(), "执行了一条指令")

    def run(self, breakpoint):
        self.session.run(breakpoint)
        self.started = time.monotonic()
        self.status.set("运行中 · 数值保留上次暂停快照；可随时点暂停")
        self.note("运行至写入断点" if breakpoint else "连续运行（10 秒后自动暂停）")
        self.controls()

    def pause(self):
        self.show(self.session.pause(), "已收到 QEMU 的暂停确认")

    def stop(self):
        if self.session:
            unchanged = self.session.close()
            self.session = None
            self.note("QEMU 已停止；输入镜像字节未变。" if unchanged else "检查失败：输入镜像发生变化。")
        self.status.set("已停止。可重新开始；每次创建全新的临时镜像。")
        self.values.set("R0  —          R1  —          PC  —\n虚拟 RAM [0x00010000]  —")
        for row in self.code.get_children():
            self.code.item(row, tags=())
        self.controls()

    def guard(self, action):
        try:
            action()
        except Exception as error:
            try:
                self.stop()
            except Exception as cleanup_error:
                self.note(f"清理未完成：{cleanup_error}")
                self.status.set("操作失败；清理未完成，请查看日志。")
            else:
                self.status.set("操作失败；本次 QEMU 已停止。")
            self.note(f"错误：{error}")

    def tick(self):
        if self.session and self.session.running:
            def check():
                if self.session.process.poll() is not None:
                    raise RuntimeError("QEMU 提前退出")
                if self.session.poll():
                    self.show(self.session.snapshot(), "已到达写入断点")
                elif time.monotonic() - self.started >= 10:
                    self.pause()
            self.guard(check)
        self.root.after(100, self.tick)

    def close(self):
        try:
            self.stop()
        finally:
            self.root.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("qemu", type=Path, nargs="?", default=Path(__file__).with_name("qemu-system-arm.exe"))
    parser.add_argument("--work-dir", type=Path, default=Path(__file__).resolve().parent / "local")
    args = parser.parse_args()
    root = tk.Tk()
    Demo(root, args.qemu.resolve(), args.work_dir.resolve())
    root.mainloop()
