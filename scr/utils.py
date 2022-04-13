from .definitions import *
from typing import Optional
from . import scr_context, match_chain, document
import urllib
import os
import sys


def is_windows() -> bool:
    return os.name == "nt"


if is_windows():
    import win32api
    import win32event
    import win32file
    import pywintypes
else:
    import select
DEFAULT_TRUNCATION_LENGTH = 200


def truncate(
    text: str,
    max_len: int = DEFAULT_TRUNCATION_LENGTH,
    trailer: str = "..."
) -> str:
    if len(text) > max_len:
        assert(max_len > len(trailer))
        return text[0: max_len - len(trailer)] + trailer
    return text


def begins(string: str, begin: str) -> bool:
    return len(string) >= len(begin) and string[0:len(begin)] == begin


def empty_string_to_none(string: Optional[str]) -> Optional[str]:
    if string == "":
        return None
    return string


def stdin_has_content(timeout: float) -> bool:
    assert timeout >= 0
    if not is_windows():
        rlist, _, _ = select.select(
            [sys.stdin], [], [], timeout
        )
        return bool(rlist)
    else:
        try:
            # without this the wait sometimes returns without there being
            # any actual data -> we woul block infinitely on the read
            win32file.FlushFileBuffers(win32api.STD_INPUT_HANDLE)
        except pywintypes.error:
            # the flush sometimes fails, too bad!
            pass
        return win32event.WaitForSingleObject(
            win32api.STD_INPUT_HANDLE, int(timeout * 1000)  # milliseconds
        ) is win32event.WAIT_OBJECT_0
