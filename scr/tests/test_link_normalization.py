import urllib.parse
from ..definitions import DocumentType
from ..scr import normalize_link
from .utils import validate_text
from .. import utils
import os


def test_windows_file_scheme_removal(pretend_windows: bool) -> None:
    cases = [
        ("file:///C:", "C:"),
        ("file:C:/foo/", "C:/foo/"),
        ("file:/C://foo/", "C://foo/"),
        ("file://C:/foo", "C:/foo"),
    ]
    for link, expected_result in cases:
        result = utils.remove_file_scheme_from_url(link)
        validate_text(f"incorrect file scheme removal for '{link}'", expected_result, result, add_newline=True)


def test_windows_file_link_normalization(pretend_windows: None) -> None:
    cases = [
        ("file://C:/foo", "", "C:/foo"),
        ("C:/foo/", "", "C:/foo"),
        ("file:///C:", "", "C:"),
    ]
    for link, base, expected_result in cases:
        res, res_parsed = normalize_link(
            link, urllib.parse.urlparse(base),
            DocumentType.FILE, "", False, False, False
        )
        assert res == urllib.parse.urlunparse(res_parsed)
        validate_text(f"wrong link normalization for '{link}'", os.path.normpath(expected_result), res, add_newline=True)


def test_url_hostname_assumption() -> None:
    res, res_parsed = normalize_link(
        "example.com", urllib.parse.urlparse(""),
        DocumentType.URL, "https", False, False, True
    )
    assert res == urllib.parse.urlunparse(res_parsed)
    validate_text("wrong link normalization", "https://example.com", res, add_newline=True)


def test_without_url_hostname_assumption() -> None:
    res, res_parsed = normalize_link(
        "example.com", urllib.parse.urlparse("https://foobar.com"),
        DocumentType.URL, "https", False, False, False
    )
    assert res == urllib.parse.urlunparse(res_parsed)
    validate_text("wrong link normalization", "https://foobar.com/example.com", res, add_newline=True)


def test_without_url_hostname_assumption_no_base() -> None:
    res, res_parsed = normalize_link(
        "example.com", None,
        DocumentType.URL, "https", False, False, False
    )
    assert res == urllib.parse.urlunparse(res_parsed)
    validate_text("wrong link normalization", "https://example.com", res, add_newline=True)
