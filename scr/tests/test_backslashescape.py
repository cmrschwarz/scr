import pytest
from typing import Optional
from ..backslashescape import unescape_string
from .utils import validate_text


@pytest.mark.parametrize(('escaped', 'unescaped', 'error_message'), [
    ("\\n", "\n", None),
    ("", "", None),
])
def test_unescape_string(escaped: str, unescaped: str, error_message: Optional[str]) -> None:
    try:
        ue = unescape_string(escaped)
    except ValueError as ve:
        assert str(ve) == error_message
        return
    assert error_message is None, "expected backslashescape to fail with an error"

    validate_text("wrong unescaped text", ue, unescaped)
