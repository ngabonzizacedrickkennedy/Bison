import os
import secrets
import socket
import sqlite3
import struct
import tempfile
from pathlib import Path

POSTGRES_PROTOCOL_VERSION = 196608
SOCKET_TIMEOUT_SECONDS = 1.5
INJECTION_DELAY_MS = 400
INJECTION_INTERVAL_SECONDS = 0.01


def _sqlite_round_trips() -> bool:
    try:
        with tempfile.TemporaryDirectory() as directory:
            expected = secrets.token_hex(6)
            connection = sqlite3.connect(Path(directory) / "probe.db")
            try:
                connection.execute("CREATE TABLE probe (value TEXT NOT NULL)")
                connection.execute("INSERT INTO probe (value) VALUES (?)", (expected,))
                connection.commit()
                row = connection.execute("SELECT value FROM probe").fetchone()
            finally:
                connection.close()
            return row is not None and row[0] == expected
    except (sqlite3.Error, OSError):
        return False


def _postgres_speaks_protocol(host: str, port: int) -> bool:
    payload = b"user\x00bison_probe\x00database\x00postgres\x00\x00"
    message = struct.pack("!ii", len(payload) + 8, POSTGRES_PROTOCOL_VERSION) + payload

    try:
        with socket.create_connection((host, port), timeout=SOCKET_TIMEOUT_SECONDS) as connection:
            connection.sendall(message)
            return connection.recv(1) in (b"R", b"E")
    except OSError:
        return False


def _screen_capture_grabs() -> bool:
    try:
        import mss
    except ImportError:
        return False

    try:
        with mss.mss() as grabber:
            shot = grabber.grab(grabber.monitors[0])
            return shot.width > 0 and shot.height > 0 and len(shot.rgb) > 0
    except Exception:
        return False


def _input_injection() -> tuple[bool, bool]:
    try:
        import tkinter

        import pyautogui
    except ImportError:
        return (False, False)

    expected = secrets.token_hex(6)
    captured = {"value": ""}

    try:
        root = tkinter.Tk()
    except Exception:
        return (True, False)

    root.title("BISON input probe")
    root.geometry("360x90+60+60")
    root.attributes("-topmost", True)

    entry = tkinter.Entry(root, width=40)
    entry.pack(padx=12, pady=24)

    def inject() -> None:
        try:
            root.focus_force()
            entry.focus_set()
            root.update()
            pyautogui.write(expected, interval=INJECTION_INTERVAL_SECONDS)
            root.update()
            captured["value"] = entry.get()
        except Exception:
            captured["value"] = ""
        finally:
            root.destroy()

    root.after(INJECTION_DELAY_MS, inject)
    root.mainloop()

    return (True, captured["value"] == expected)


def run_probes() -> dict[str, bool]:
    available, verified = _input_injection()

    return {
        "sqlite": _sqlite_round_trips(),
        "postgres": _postgres_speaks_protocol(
            os.environ.get("BISON_POSTGRES_HOST", "127.0.0.1"),
            int(os.environ.get("BISON_POSTGRES_PORT", "5432")),
        ),
        "input_injection_available": available,
        "input_injection_verified": verified,
        "screen_capture": _screen_capture_grabs(),
    }
