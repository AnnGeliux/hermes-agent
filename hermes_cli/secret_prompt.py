"""Secret input prompts with masked typing feedback."""

from __future__ import annotations

import getpass
import os
import sys
from collections.abc import Callable


_BACKSPACE_CHARS = {"\b", "\x7f"}
_ENTER_CHARS = {"\r", "\n"}
_EOF_CHARS = {"\x04", "\x1a", ""}  # "" == stream closed


def _collect_masked_input(
    read_char: Callable[[], str], write: Callable[[str], object], prompt: str, *, mask: str = "*",
) -> str:
    """Read one secret line while writing a mask character per typed char."""
    value: list[str] = []
    write(prompt)
    while True:
        ch = read_char()
        if ch in _ENTER_CHARS:
            write("\r\n")
            return "".join(value)
        if ch == "\x03":
            write("\r\n")
            raise KeyboardInterrupt
        if ch in _EOF_CHARS:
            write("\r\n")
            raise EOFError
        if ch in _BACKSPACE_CHARS:
            if value:
                value.pop()
                write("\b \b")
            continue
        if ch == "\x1b":
            # Terminals send escape-prefixed navigation/delete sequences; they must not become
            # secret text.
            continue
        value.append(ch)
        if mask:
            write(mask)


def masked_secret_prompt(prompt: str, *, mask: str = "*") -> str:
    """Prompt for a secret while showing masked typing feedback.

    Falls back to ``getpass.getpass`` when stdin/stdout are not interactive or when raw terminal
    handling is unavailable.

    On Windows with a redirected stdin (``< NUL``, ``< /dev/null``, a pipe) ``getpass`` is
    ``win_getpass``: it ignores stdin, writes the prompt straight to the console and blocks in
    ``msvcrt.getwch()`` forever instead of raising ``EOFError`` (#136736).  That case raises
    ``EOFError`` directly — the same outcome the POSIX path produces when stdin is exhausted.
    """
    if _windows_console_read_would_block():
        raise EOFError("EOF when reading a line")
    if not _stream_is_tty(sys.stdin) or not _stream_is_tty(sys.stdout):
        return getpass.getpass(prompt)
    masked = _masked_secret_prompt_windows if os.name == "nt" else _masked_secret_prompt_posix
    try:
        return masked(prompt, mask=mask)
    except (KeyboardInterrupt, EOFError):
        raise
    except Exception:
        return getpass.getpass(prompt)


def _stream_is_tty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def stdin_is_console() -> bool:
    """True only when stdin can actually deliver an interactive, non-blocking line."""
    if not _stream_is_tty(sys.stdin):
        return False
    return not _windows_console_read_would_block()


def _windows_console_read_would_block() -> bool:
    """True when ``getpass``/``msvcrt`` would read the console and block forever.

    Windows' ``getpass`` is ``win_getpass``: it ignores stdin and calls ``msvcrt.getwch()``.
    ``sys.stdin.isatty()`` is True for the NUL device (a character device) and for a console,
    so a ``< /dev/null`` redirect still looked interactive and ``hermes auth add`` hung on the
    console instead of failing on exhausted stdin (#136736).  ``GetConsoleMode`` succeeds only
    for a real console handle, so it tells the two apart.  Non-Windows and stream doubles with
    no real ``fileno()`` return False, leaving the plain ``getpass`` fallback untouched.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        mode = ctypes.c_uint()
        return not ctypes.windll.kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode))
    except (AttributeError, OSError, ValueError):
        # A stream double or a closed fd has no console handle to query — the same
        # "cannot read here" outcome the guard exists to report, not an error.
        return False


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _masked_secret_prompt_windows(prompt: str, *, mask: str) -> str:
    import msvcrt

    def read_char() -> str:
        ch = msvcrt.getwch()
        if ch in {"\x00", "\xe0"}:
            msvcrt.getwch()
            return "\x1b"
        return ch

    return _collect_masked_input(read_char, _write, prompt, mask=mask)


def _masked_secret_prompt_posix(prompt: str, *, mask: str) -> str:
    import termios
    import tty
    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return _collect_masked_input(lambda: sys.stdin.read(1), _write, prompt, mask=mask)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
