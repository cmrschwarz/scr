import re
from typing import Union

# in some cases pytest's attemt to highlight string differences makes the output
# pretty unreadable, so we rust raise a ValueError
# with the expected and received strings in the exception message instead
USE_PYTEST_ASSERTIONS = False


def validate_text(err_msg: str, expected: str, received: str, regex: bool = False, add_newline: bool = False) -> None:
    if regex:
        if not re.match(expected, received, re.DOTALL):
            raise ValueError(
                f"{err_msg}:\n{received_expected_strs(received, expected, add_newline)}"
            )
    else:
        if USE_PYTEST_ASSERTIONS:
            assert expected == received, err_msg
        elif expected != received:
            raise ValueError(
                f"{err_msg}:\n{received_expected_strs(received, expected, add_newline)}"
            )


def received_expected_strs(received: str, expected: str, add_newline: bool = False) -> str:
    if add_newline:
        expected += "\n"
        received += "\n"
    return f"{'-' * 36}received{'-' * 36}\n{received}{'-' * 36}expected{'-' * 36}\n{expected}{'-' * 80}"


def join_lines(lines: Union[list[str], str]) -> str:
    if not isinstance(lines, list):
        return lines
    return "\n".join(lines) + "\n"
