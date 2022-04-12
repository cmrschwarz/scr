from .definitions import *
from typing import Optional
from . import scr_context, match_chain, document
import urllib
import os


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
