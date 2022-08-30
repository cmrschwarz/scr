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
FILE_SCHEME_LEN = len("file:")


def truncate(
    text: str,
    max_len: int = DEFAULT_TRUNCATION_LENGTH,
    trailer: str = "..."
) -> str:
    if len(text) > max_len:
        assert max_len > len(trailer)
        return text[0: max_len - len(trailer)] + trailer
    return text


def not_none(val: Optional[T]) -> T:
    assert val is not None
    return val


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


def unique_not_none(*values: Optional[T]) -> list[T]:
    # since mypy complains about lambdas in filters, we use this
    res = set()
    for v in values:
        if v is not None:
            res.add(v)
    return list(res)


def stdin_has_content(timeout: float) -> bool:
    assert timeout >= 0
    if is_windows():
        return windows.stdin_has_content(timeout)
    else:
        rlist, _, _ = select.select(
            [sys.stdin], [], [], timeout
        )
        return bool(rlist)


def remove_file_scheme_from_url(url: str) -> str:
    offs = len("file:")
    assert url[:offs] == "file:"
    if url[offs:offs+1] != "/":
        return url[offs:]
    while offs < len(url):
        if url[offs] != "/":
            break
        offs += 1

    # browsers turn windows paths like 'C:\foobar' into "file:///C:/foobar"
    # which does not work with python's os.path, so we hack in a fix
    # that removes that leading slash from the path.
    # once we do that, we always have to always keep the 'file://',
    # otherwise urllib will think that C: is a scheme, see normalize_selenium_base_link
    if is_windows() and re.match("[A-Za-z]:", url[offs:]):
        return url[offs:]
    return url[offs-1:]


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
