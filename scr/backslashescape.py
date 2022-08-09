import re
from typing import cast

BSE_X_REGEX_MATCH = re.compile("[0-9A-Fa-f]{2}")
BSE_U_REGEX_MATCH = re.compile("[0-9A-Fa-f]{4}")


def parse_bse_u(match: re.Match[str]) -> str:
    code = match[3]
    if not BSE_U_REGEX_MATCH.match(code):
        raise ValueError(f"invalid escape code \\u{code}")
    code = (b"\\u" + code.encode("ascii")).decode("unicodeescape")
    return "".join(map(lambda x: cast(str, x) if x else "", [match[1], match[2], code]))


def parse_bse_x(match: re.Match[str]) -> str:
    code = match[3]
    if not BSE_X_REGEX_MATCH.match(code):
        raise ValueError(f"invalid escape code \\x{code}")
    code = (b"\\udc" + code.encode("ascii")).decode("unicode_escape")
    return "".join(map(lambda x: cast(str, x) if x else "", [match[1], match[2], code]))


def parse_bse_o(match: re.Match[str]) -> str:
    code = match[3]
    res = {
        "a": "\a",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "": None,
    }.get(code, None)
    if res is None:
        if code == "":
            raise ValueError("unterminated escape sequence '\\'")
        raise ValueError(f"invalid escape code \\{code}")
    return "".join(map(lambda x: cast(str, x) if x else "", [match[1], match[2], res]))


BSE_PATTERNS = [
    (re.compile(r"(^|[^\\])(\\\\)*\\u(.{0,4})"), parse_bse_u),
    (re.compile(r"(^|[^\\])(\\\\)*\\x(.{0,2})"), parse_bse_x),
    (re.compile(
        "(^|[^\\\\])(\\\\\\\\)*\\\\([rntfb\\'\\\"\\\\]|$)"), parse_bse_o),
]


def unescape_string(txt: str) -> str:
    for regex, parser in BSE_PATTERNS:
        txt = regex.sub(parser, txt)
    return txt
