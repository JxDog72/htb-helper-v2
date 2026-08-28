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

_pause = threading.Event()
_log_lock = threading.Lock()
_log_fp = None
_pty_master = None
_windows_stdin = None


def session_paused():
    return _pause.is_set()


def set_session_paused(paused: bool) -> str:
    """Pause or resume writing to the session log. Terminal I/O continues."""
    global _log_fp
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if paused:
        _pause.set()
        msg = f"\n===== LOGGING PAUSED {stamp} =====\n"
    else:
        _pause.clear()
        msg = f"\n===== LOGGING RESUMED {stamp} =====\n"
    with _log_lock:
        if _log_fp is not None:
            try:
                _log_fp.write(msg)
                _log_fp.flush()
            except Exception:
                pass
    return msg.strip()


def append_to_session_log(text: str) -> bool:
    """Write extra text into the live session log (GUI tool runs, etc.)."""
    global _log_fp
    chunk = str(text or "")
    if not chunk:
        return False
    if not chunk.endswith("\n"):
        chunk += "\n"
    with _log_lock:
        if _log_fp is None:
            return False
        try:
            _log_fp.write(chunk)
            _log_fp.flush()
            return True
        except Exception:
            return False


def inject_to_session(command: str) -> bool:
    """Type a command into the live logged shell, as if the student typed it."""
    line = str(command or "").rstrip()
    if not line:
        return False
    payload = line + "\n"
    if os.name == "nt":
        stdin = _windows_stdin
        if stdin is None:
            return False
        try:
            data = payload.replace("\n", "\r\n").encode(sys.stdout.encoding or "utf-8", errors="replace")
            stdin.write(data)
            stdin.flush()
            return True
        except Exception:
            return False
    master = _pty_master
    if master is None:
        return False
    try:
        os.write(master, payload.encode("utf-8", errors="replace"))
        return True
    except OSError:
        return False


def run_logged_shell(log_file: Path) -> int:
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        return _run_windows_piped(log_file)
    return _run_unix(log_file)


def _run_unix(log_file: Path) -> int:
    """PTY capture so pause/resume can stop writing without killing the shell."""
    import pty
    import select
    import termios
    import tty

    global _log_fp, _pty_master
    shell = os.environ.get("SHELL") or "/bin/bash"
    _pause.clear()
    log = log_file.open("a", encoding="utf-8", errors="replace")
    log.write(
        f"===== HTB Helper session log (console capture) =====\n"
        f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Shell: {shell}\n"
        f"====================================================\n"
    )
    log.flush()
    _log_fp = log
    print("[+] Console capture is ON. Pause/Resume is in the Session menu in the GUI.")
    print("[+] Ctrl+C stops the current command, not the logger.")
    print("[+] Tools → Send to terminal types the command into this shell.")
    print("[+] Type 'exit' when the session is finished.\n")

    def _copy_winsize(master_fd):
        try:
            import fcntl
            import struct
            packed = fcntl.ioctl(sys.stdin.fileno(), termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0))
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, packed)
        except Exception:
            pass

    def _fallback_script():
        print("[!] PTY capture failed; falling back to `script` (Send to terminal will not work).")
        if shutil.which("script"):
            if sys.platform == "darwin":
                cmd = ["script", "-q", "-a", "-F", str(log_file), shell]
            else:
                cmd = ["script", "-q", "-f", "-a", "-c", shell, str(log_file)]
            result = subprocess.run(cmd, check=False)
            return result.returncode or 0
        return 1

    old_sig = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    old_term = None
    pid = None
    try:
        pid, master = pty.fork()
    except OSError:
        try:
            signal.signal(signal.SIGINT, old_sig)
        except Exception:
            pass
        code = _fallback_script()
        with _log_lock:
            try:
                log.write(f"\n===== session ended {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n")
                log.close()
            except Exception:
                pass
            _log_fp = None
        return code

    if pid == 0:
        os.execvp(shell, [shell])
        os._exit(127)

    _pty_master = master
    _copy_winsize(master)
    try:
        old_term = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())
    except Exception:
        old_term = None

    try:
        while True:
            try:
                readable, _, _ = select.select([master, sys.stdin], [], [], 0.2)
            except (InterruptedError, ValueError, OSError):
                break
            if sys.stdin in readable:
                try:
                    data = os.read(sys.stdin.fileno(), 1024)
                except OSError:
                    data = b""
                if not data:
                    break
                try:
                    os.write(master, data)
                except OSError:
                    break
            if master in readable:
                try:
                    data = os.read(master, 1024)
                except OSError:
                    data = b""
                if not data:
                    break
                try:
                    os.write(sys.stdout.fileno(), data)
                except OSError:
                    pass
                if data and not _pause.is_set():
                    with _log_lock:
                        try:
                            log.write(data.decode("utf-8", errors="replace"))
                            log.flush()
                        except Exception:
                            pass
        if pid:
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        return 0
    finally:
        _pty_master = None
        if old_term is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_term)
            except Exception:
                pass
        try:
            signal.signal(signal.SIGINT, old_sig)
        except Exception:
            pass
        with _log_lock:
            try:
                log.write(f"\n===== session ended {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n")
                log.close()
            except Exception:
                pass
            _log_fp = None


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

    global _log_fp, _windows_stdin
    _pause.clear()
    log = log_file.open("a", encoding="utf-8", errors="replace")
    log.write(header)
    log.flush()
    _log_fp = log
    log_lock = _log_lock

    proc = subprocess.Popen(
        [comspec, "/D", "/K", "prompt $P$G"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        creationflags=CREATE_NEW_PROCESS_GROUP,
    )
    _windows_stdin = proc.stdin

    stop = threading.Event()

    def write_log(text: str):
        if _pause.is_set():
            return
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
        with _log_lock:
            log.write(f"\n===== session ended {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            log.close()
            _log_fp = None
            _windows_stdin = None

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
