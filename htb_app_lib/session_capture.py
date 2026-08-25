"""Full-console session capture.

Unix: util-linux `script` (records ping/traceroute).
Windows: cmd.exe with stdout/stderr pipes. Start-Transcript only keeps
PowerShell cmdlets (pwd/dir) and drops native .exe output (ipconfig, ping,
tracert, nmap). Pipes capture that output. Ctrl+C is sent to the running
command, not the logger.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import shutil
import signal
import subprocess
import sys
import threading


def run_logged_shell(log_file: Path) -> int:
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        return _run_windows_piped(log_file)
    return _run_unix(log_file)


def _run_unix(log_file: Path) -> int:
    if not shutil.which("script"):
        print("[-] 'script' not found. Install bsdutils:  sudo apt install bsdutils")
        return 1
    shell = os.environ.get("SHELL") or "/bin/bash"
    if sys.platform == "darwin":
        cmd = ["script", "-q", "-a", "-F", str(log_file), shell]
    else:
        cmd = ["script", "-q", "-f", "-a", "-c", shell, str(log_file)]
    print("[+] Ctrl+C stops the current command (ping/traceroute), not the logger.")
    print("[+] Type 'exit' when the session is finished.\n")
    old = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode or 0
    finally:
        try:
            signal.signal(signal.SIGINT, old)
        except Exception:
            pass


def _run_windows_piped(log_file: Path) -> int:
    """Log a real cmd.exe session, including native tools like ipconfig/ping."""
    import ctypes
    from ctypes import wintypes

    comspec = os.environ.get("COMSPEC") or r"C:\Windows\System32\cmd.exe"
    encoding = sys.stdout.encoding or "utf-8"
    CREATE_NEW_PROCESS_GROUP = 0x00000200

    header = (
        f"===== HTB Helper session log (console capture) =====\n"
        f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Shell: {comspec}\n"
        f"====================================================\n"
    )

    log = log_file.open("a", encoding="utf-8", errors="replace")
    log.write(header)
    log.flush()
    log_lock = threading.Lock()

    proc = subprocess.Popen(
        [comspec, "/D", "/K", "prompt $P$G"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        creationflags=CREATE_NEW_PROCESS_GROUP,
    )

    stop = threading.Event()

    def write_log(text: str):
        with log_lock:
            log.write(text)
            log.flush()

    def pump_out():
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read(256)
            if not chunk:
                break
            try:
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            except Exception:
                pass
            write_log(chunk.decode(encoding, errors="replace"))

    def pump_in():
        assert proc.stdin is not None
        fd = sys.stdin.fileno()
        while not stop.is_set() and proc.poll() is None:
            try:
                chunk = os.read(fd, 256)
            except OSError:
                break
            if not chunk:
                break
            try:
                proc.stdin.write(chunk)
                proc.stdin.flush()
            except (BrokenPipeError, OSError):
                break

    t_out = threading.Thread(target=pump_out, daemon=True)
    t_in = threading.Thread(target=pump_in, daemon=True)
    t_out.start()
    t_in.start()

    if os.environ.get("HTB_SESSION_SELFTEST"):
        assert proc.stdin is not None
        proc.stdin.write(b"ping -n 1 127.0.0.1\r\nipconfig\r\nexit\r\n")
        proc.stdin.flush()

    HandlerType = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

    def _ctrl(ctrl_type):
        if ctrl_type in (0, 1):  # CTRL_C / CTRL_BREAK
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception:
                pass
            return True
        return False

    ctrl_handler = HandlerType(_ctrl)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
    kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL
    kernel32.SetConsoleCtrlHandler(ctrl_handler, True)

    print("[+] Console capture is ON. ipconfig / ping / tracert / nmap output is logged.")
    print("[+] Ctrl+C stops the current command, not this logger.")
    print("[+] Type 'exit' when the session is finished.\n")

    try:
        proc.wait()
    finally:
        stop.set()
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        t_out.join(timeout=2)
        kernel32.SetConsoleCtrlHandler(ctrl_handler, False)
        log.write(f"\n===== session ended {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        log.close()

    return proc.returncode or 0


def decode_log_bytes(data: bytes) -> str:
    """Decode session logs whether they are UTF-8 (new) or UTF-16 (old transcripts)."""
    if not data:
        return ""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    sample = data[:200]
    if sample.count(b"\x00") > max(8, len(sample) // 4):
        return data.decode("utf-16-le", errors="replace")
    return data.decode("utf-8", errors="replace")
