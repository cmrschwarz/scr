import inspect
from . import windows
from typing import Optional, Callable
import platform
import sys
import re
import select
from .definitions import T


def is_windows() -> bool:
    return platform.system() == 'Windows'


def is_osx() -> bool:
    return platform.system() == 'Darwin'


def is_linux() -> bool:
    return platform.system() == 'Linux'


DEFAULT_TRUNCATION_LENGTH = 200


def truncate(
    text: str,
    max_len: int = DEFAULT_TRUNCATION_LENGTH,
    trailer: str = "..."
) -> str:
    if len(text) > max_len:
        assert max_len > len(trailer)
        return text[0: max_len - len(trailer)] + trailer
    return text


def begins(string: str, begin: str) -> bool:
    return len(string) >= len(begin) and string[0:len(begin)] == begin


def empty_string_to_none(string: Optional[str]) -> Optional[str]:
    if string == "":
        return None
    return string


def choose_first_not_none(*tries: Callable[[], Optional[T]]) -> Optional[T]:
    for t in tries:
        res = t()
        if res is not None:
            return res
    return None


def stdin_has_content(timeout: float) -> bool:
    assert timeout >= 0
    if sys.platform != 'win32':
        rlist, _, _ = select.select(
            [sys.stdin], [], [], timeout
        )
        return bool(rlist)
    else:
        return windows.stdin_has_content(timeout)


def remove_file_scheme_from_url(url: str) -> str:
    offs = len("file:")
    assert url[:offs] == "file:"
    for i in range(2):
        if url[offs] == "/":
            offs += 1
    url = url[offs:]
    # browsers turn windows paths like 'C:\foobar' into "file:///C:/foobar"
    # which does not fly with pythons os.path, so we hack in a fix
    # that removes that leading slash from the path
    # once we do that, urllib thinks that C: is a scheme,
    # so we have to include file://, see handle_widows_paths normalize_link
    if is_windows() and re.match("/[A-Za-z]:/", url):
        url = url[1:]
    return url


def is_debugger_attached() -> bool:
    debugger_frames = [
        "pydevd.py",
        "pydevd_runpy.py"
    ]
    stack = inspect.stack()
    for frame in stack:
        for df in debugger_frames:
            if frame[1].endswith(df):
                return True
    return False
