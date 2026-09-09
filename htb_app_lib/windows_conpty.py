"""Windows ConPTY logged cmd.exe (stdlib ctypes, no pip).

Piped cmd.exe is not a console: no prompt/echo, output can sit buffered,
and a Ctrl+C handler that swallows the key leaves the logger stuck.
ConPTY gives cmd a real console so typing and Ctrl+C work.
"""

from __future__ import annotations

from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import ctypes
import os
import sys
import threading
import time

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

HPCON = wintypes.HANDLE
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x00000100
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
ENABLE_PROCESSED_OUTPUT = 0x0001
ENABLE_WRAP_AT_EOL_OUTPUT = 0x0002
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004
ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
CTRL_C_EVENT = 0
CTRL_BREAK_EVENT = 1
STILL_ACTIVE = 259
S_OK = 0


class COORD(ctypes.Structure):
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [
        ("Left", wintypes.SHORT),
        ("Top", wintypes.SHORT),
        ("Right", wintypes.SHORT),
        ("Bottom", wintypes.SHORT),
    ]


class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", COORD),
        ("dwCursorPosition", COORD),
        ("wAttributes", wintypes.WORD),
        ("srWindow", SMALL_RECT),
        ("dwMaximumWindowSize", COORD),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", STARTUPINFOW),
        ("lpAttributeList", ctypes.c_void_p),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


kernel32.CreatePipe.argtypes = [
    ctypes.POINTER(wintypes.HANDLE),
    ctypes.POINTER(wintypes.HANDLE),
    ctypes.POINTER(SECURITY_ATTRIBUTES),
    wintypes.DWORD,
]
kernel32.CreatePipe.restype = wintypes.BOOL
kernel32.CreatePseudoConsole.argtypes = [
    COORD,
    wintypes.HANDLE,
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
]
kernel32.CreatePseudoConsole.restype = ctypes.c_long  # HRESULT
kernel32.ClosePseudoConsole.argtypes = [wintypes.HANDLE]
kernel32.ClosePseudoConsole.restype = None
kernel32.InitializeProcThreadAttributeList.argtypes = [
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
kernel32.UpdateProcThreadAttribute.argtypes = [
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
kernel32.DeleteProcThreadAttributeList.restype = None
kernel32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.BOOL,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    ctypes.POINTER(PROCESS_INFORMATION),
]
kernel32.CreateProcessW.restype = wintypes.BOOL
kernel32.ReadFile.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
]
kernel32.ReadFile.restype = wintypes.BOOL
kernel32.WriteFile.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
]
kernel32.WriteFile.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.TerminateProcess.restype = wintypes.BOOL
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL
kernel32.GetConsoleScreenBufferInfo.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(CONSOLE_SCREEN_BUFFER_INFO),
]
kernel32.GetConsoleScreenBufferInfo.restype = wintypes.BOOL
kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetConsoleMode.restype = wintypes.BOOL
kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.SetConsoleMode.restype = wintypes.BOOL
kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
kernel32.GetStdHandle.restype = wintypes.HANDLE
kernel32.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL
kernel32.PeekNamedPipe.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.PeekNamedPipe.restype = wintypes.BOOL
kernel32.GetFileType.argtypes = [wintypes.HANDLE]
kernel32.GetFileType.restype = wintypes.DWORD

FILE_TYPE_CHAR = 2

STD_INPUT_HANDLE = wintypes.DWORD(-10)
STD_OUTPUT_HANDLE = wintypes.DWORD(-11)
INFINITE = 0xFFFFFFFF
HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)


def available() -> bool:
    return os.name == "nt" and hasattr(kernel32, "CreatePseudoConsole")


class PipeWriter:
    """File-like write/flush/close over a Windows HANDLE (for Send to terminal)."""

    def __init__(self, handle):
        self._h = handle

    def write(self, data):
        if isinstance(data, str):
            data = data.encode(sys.stdout.encoding or "utf-8", errors="replace")
        if not data:
            return 0
        written = wintypes.DWORD(0)
        ok = kernel32.WriteFile(self._h, data, len(data), ctypes.byref(written), None)
        if not ok:
            raise OSError("WriteFile failed")
        return written.value

    def flush(self):
        return None

    def close(self):
        return None


def _console_size():
    info = CONSOLE_SCREEN_BUFFER_INFO()
    h = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
    if kernel32.GetConsoleScreenBufferInfo(h, ctypes.byref(info)):
        width = info.srWindow.Right - info.srWindow.Left + 1
        height = info.srWindow.Bottom - info.srWindow.Top + 1
        if width > 0 and height > 0:
            return COORD(width, height)
    return COORD(120, 30)


def _enable_vt_output():
    h = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
    mode = wintypes.DWORD(0)
    if not kernel32.GetConsoleMode(h, ctypes.byref(mode)):
        return
    kernel32.SetConsoleMode(
        h,
        mode.value
        | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        | ENABLE_PROCESSED_OUTPUT
        | ENABLE_WRAP_AT_EOL_OUTPUT,
    )


def _set_raw_input():
    """Let ConPTY echo/edit; don't echo locally (that doubles every key)."""
    h = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    mode = wintypes.DWORD(0)
    if not kernel32.GetConsoleMode(h, ctypes.byref(mode)):
        return None
    old = mode.value
    kernel32.SetConsoleMode(
        h,
        (old & ~ENABLE_ECHO_INPUT & ~ENABLE_LINE_INPUT)
        | ENABLE_PROCESSED_INPUT
        | ENABLE_VIRTUAL_TERMINAL_INPUT,
    )
    return old


def _restore_input(old_mode):
    if old_mode is None:
        return
    h = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    kernel32.SetConsoleMode(h, old_mode)


def _drain_inject_file(path, writer):
    if not path:
        return
    p = Path(path)
    if not p.is_file():
        return
    try:
        text = p.read_text(encoding="utf-8")
        p.write_text("", encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            writer.write((line + "\r\n").encode("utf-8", errors="replace"))
        except Exception:
            return


def run(*, log, pause_event, log_lock, set_stdin, encoding="utf-8", startup_input=None, inject_file=None) -> int:
    """Run cmd.exe attached to a ConPTY; copy I/O to this console and the session log."""
    if not available():
        raise RuntimeError("CreatePseudoConsole is not available on this Windows build.")

    comspec = os.environ.get("COMSPEC") or r"C:\Windows\System32\cmd.exe"
    h_pty_in = wintypes.HANDLE()
    h_parent_out = wintypes.HANDLE()  # parent writes here → PTY input
    h_parent_in = wintypes.HANDLE()  # parent reads here ← PTY output
    h_pty_out = wintypes.HANDLE()

    if not kernel32.CreatePipe(ctypes.byref(h_pty_in), ctypes.byref(h_parent_out), None, 0):
        raise OSError("CreatePipe input failed")
    if not kernel32.CreatePipe(ctypes.byref(h_parent_in), ctypes.byref(h_pty_out), None, 0):
        raise OSError("CreatePipe output failed")

    h_pc = wintypes.HANDLE()
    hr = kernel32.CreatePseudoConsole(_console_size(), h_pty_in, h_pty_out, 0, ctypes.byref(h_pc))
    kernel32.CloseHandle(h_pty_in)
    kernel32.CloseHandle(h_pty_out)
    if hr != S_OK:
        kernel32.CloseHandle(h_parent_in)
        kernel32.CloseHandle(h_parent_out)
        raise OSError(f"CreatePseudoConsole failed HRESULT=0x{hr & 0xFFFFFFFF:08X}")

    attr_size = ctypes.c_size_t(0)
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attr_size))
    attr_buf = ctypes.create_string_buffer(attr_size.value)
    if not kernel32.InitializeProcThreadAttributeList(attr_buf, 1, 0, ctypes.byref(attr_size)):
        kernel32.ClosePseudoConsole(h_pc)
        raise OSError("InitializeProcThreadAttributeList failed")
    # Microsoft/node-pty pass the HPCON handle itself as lpValue, not &handle.
    if not kernel32.UpdateProcThreadAttribute(
        attr_buf,
        0,
        PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
        ctypes.c_void_p(h_pc.value),
        ctypes.sizeof(wintypes.HANDLE),
        None,
        None,
    ):
        kernel32.DeleteProcThreadAttributeList(attr_buf)
        kernel32.ClosePseudoConsole(h_pc)
        raise OSError("UpdateProcThreadAttribute failed")

    siex = STARTUPINFOEXW()
    siex.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
    # Keep the child off this console; otherwise cmd pops a 3rd window and
    # bypasses the PTY (session.log stays empty).
    siex.StartupInfo.dwFlags = STARTF_USESTDHANDLES
    siex.StartupInfo.hStdInput = None
    siex.StartupInfo.hStdOutput = None
    siex.StartupInfo.hStdError = None
    siex.lpAttributeList = ctypes.cast(attr_buf, ctypes.c_void_p)

    cmdline = ctypes.create_unicode_buffer(f'"{comspec}" /D /K')
    cwd = os.getcwd()
    pi = PROCESS_INFORMATION()
    ok = kernel32.CreateProcessW(
        None,
        cmdline,
        None,
        None,
        False,
        EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW,
        None,
        cwd,
        ctypes.byref(siex),
        ctypes.byref(pi),
    )
    if not ok:
        err = ctypes.get_last_error()
        kernel32.DeleteProcThreadAttributeList(attr_buf)
        kernel32.ClosePseudoConsole(h_pc)
        kernel32.CloseHandle(h_parent_in)
        kernel32.CloseHandle(h_parent_out)
        raise OSError(f"CreateProcessW failed ({err})")

    writer = PipeWriter(h_parent_out)
    set_stdin(writer)
    _enable_vt_output()
    old_in_mode = _set_raw_input()
    stop = threading.Event()
    last_ctrl = [0.0]
    h_con_in = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    h_con_out = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)

    def write_log(text: str):
        if pause_event.is_set():
            return
        with log_lock:
            try:
                log.write(text)
                log.flush()
            except Exception:
                pass

    def _drain_out():
        buf = ctypes.create_string_buffer(512)
        n = wintypes.DWORD(0)
        avail = wintypes.DWORD(0)
        if not kernel32.PeekNamedPipe(h_parent_in, None, 0, None, ctypes.byref(avail), None):
            return False
        if avail.value == 0:
            return True
        to_read = min(avail.value, 512)
        if not kernel32.ReadFile(h_parent_in, buf, to_read, ctypes.byref(n), None) or n.value == 0:
            return False
        chunk = buf.raw[: n.value]
        written = wintypes.DWORD(0)
        kernel32.WriteFile(h_con_out, chunk, n.value, ctypes.byref(written), None)
        write_log(chunk.decode(encoding, errors="replace"))
        return True

    def pump_out():
        while not stop.is_set():
            if not _drain_out():
                break
            if kernel32.WaitForSingleObject(pi.hProcess, 0) == 0:
                _drain_out()
                break
            time.sleep(0.02)

    def pump_in():
        is_console = kernel32.GetFileType(h_con_in) == FILE_TYPE_CHAR
        if not is_console:
            return
        try:
            import msvcrt
        except ImportError:
            return
        while not stop.is_set() and kernel32.WaitForSingleObject(pi.hProcess, 0) != 0:
            if not msvcrt.kbhit():
                time.sleep(0.02)
                continue
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                msvcrt.getwch()
                continue
            data = b"\r\n" if ch == "\r" else ch.encode(encoding, errors="replace")
            written = wintypes.DWORD(0)
            if not kernel32.WriteFile(h_parent_out, data, len(data), ctypes.byref(written), None):
                break

    def on_ctrl(ctrl_type):
        if ctrl_type not in (CTRL_C_EVENT, CTRL_BREAK_EVENT):
            return False
        now = time.monotonic()
        double = (now - last_ctrl[0]) < 1.5
        last_ctrl[0] = now
        try:
            writer.write(b"\x03")
        except Exception:
            pass
        if double:
            try:
                kernel32.TerminateProcess(pi.hProcess, 1)
            except Exception:
                pass
            try:
                kernel32.ClosePseudoConsole(h_pc)
            except Exception:
                pass
        return True

    ctrl_handler = HandlerRoutine(on_ctrl)
    kernel32.SetConsoleCtrlHandler(ctrl_handler, True)

    t_out = threading.Thread(target=pump_out, daemon=True)
    t_in = threading.Thread(target=pump_in, daemon=True)
    t_out.start()
    t_in.start()

    if startup_input is None and os.environ.get("HTB_SESSION_SELFTEST"):
        startup_input = b"echo HTB_CONPTY_OK\r\nexit\r\n"
    if startup_input:
        time.sleep(0.2)
        try:
            writer.write(startup_input)
        except Exception:
            pass

    WAIT_TIMEOUT = 258
    code = wintypes.DWORD(0)
    try:
        while True:
            wr = kernel32.WaitForSingleObject(pi.hProcess, 200)
            _drain_inject_file(inject_file, writer)
            if wr != WAIT_TIMEOUT:
                break
        kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    finally:
        stop.set()
        kernel32.SetConsoleCtrlHandler(ctrl_handler, False)
        _restore_input(old_in_mode)
        set_stdin(None)
        try:
            kernel32.ClosePseudoConsole(h_pc)
        except Exception:
            pass
        t_out.join(timeout=1)
        kernel32.DeleteProcThreadAttributeList(attr_buf)
        kernel32.CloseHandle(pi.hThread)
        kernel32.CloseHandle(pi.hProcess)
        kernel32.CloseHandle(h_parent_in)
        kernel32.CloseHandle(h_parent_out)
        with log_lock:
            try:
                log.write(
                    f"\n===== session ended {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n"
                )
                log.flush()
            except Exception:
                pass

    return 0 if code.value == STILL_ACTIVE else int(code.value)
