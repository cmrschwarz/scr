from typing import TypeVar
from enum import Enum, IntEnum

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")

# because for python, sys.argv[0] does not reflect what the user typed anyways,
# we just use this fixed value for --help etc.
SCRIPT_NAME = "scr"
VERSION = "0.8.0"

SCR_USER_AGENT = f"{SCRIPT_NAME}/{VERSION}"
FALLBACK_DOCUMENT_SCHEME = "https"
DEFAULT_TIMEOUT_SECONDS = 30
URL_FILENAME_MAX_LEN = 256


# mimetype to use for selenium downloading to avoid triggering pdf viewers etc.
DUMMY_MIMETYPE = "application/zip"

DEFAULT_CPF = "{c}\\n"
DEFAULT_CWF = "{c}"
DEFAULT_CSF = "{fn}"
DEFAULT_ESCAPE_SEQUENCE = "<END>"


class ScrSetupError(Exception):
    pass


class ScrFetchError(Exception):
    pass


class ScrMatchError(Exception):
    pass


class InteractiveResult(Enum):
    ACCEPT = 0
    REJECT = 1
    EDIT = 2
    INSPECT = 3
    SKIP_CHAIN = 4
    SKIP_DOC = 5
    ACCEPT_CHAIN = 6
    ERROR = 0


class SeleniumVariant(Enum):
    DISABLED = 0
    CHROME = 1
    FIREFOX = 2
    TORBROWSER = 3

    @staticmethod
    def default() -> 'SeleniumVariant':
        return SeleniumVariant.FIREFOX

    def enabled(self) -> bool:
        return self != SeleniumVariant.DISABLED


class SeleniumDownloadStrategy(Enum):
    EXTERNAL = 0
    INTERNAL = 1
    FETCH = 2


class SeleniumStrategy(Enum):
    DISABLED = 0
    PLAIN = 1
    ANYMATCH = 2
    INTERACTIVE = 3
    DEDUP = 4


class Verbosity(IntEnum):
    ERROR = 1
    WARN = 2
    INFO = 3
    DEBUG = 4


class DocumentType(Enum):
    URL = 1
    FILE = 2
    RFILE = 3
    CONTENT_MATCH = 4
    CONTENT_FILE = 999  # special type for the document as content optimization

    def derived_type(self) -> 'DocumentType':
        if self == DocumentType.RFILE:
            return DocumentType.URL
        if self == DocumentType.CONTENT_FILE:
            return DocumentType.FILE
        return self

    def url_handling_type(self) -> 'DocumentType':
        if self == DocumentType.RFILE:
            return DocumentType.FILE
        return self


document_type_display_dict: dict[DocumentType, str] = {
    DocumentType.URL: "url",
    DocumentType.FILE: "file",
    DocumentType.RFILE: "rfile",
    DocumentType.CONTENT_MATCH: "content match from"
}

selenium_variants_dict: dict[str, SeleniumVariant] = {
    "disabled": SeleniumVariant.DISABLED,
    "tor": SeleniumVariant.TORBROWSER,
    "firefox": SeleniumVariant.FIREFOX,
    "chrome": SeleniumVariant.CHROME
}

selenium_variants_display_dict: dict[SeleniumVariant, str] = {
    SeleniumVariant.DISABLED: "disabled",
    SeleniumVariant.TORBROWSER: "Tor Browser",
    SeleniumVariant.FIREFOX: "Firefox",
    SeleniumVariant.CHROME: "Chrome"
}


selenium_download_strategies_dict: dict[str, SeleniumDownloadStrategy] = {
    "external": SeleniumDownloadStrategy.EXTERNAL,
    "internal": SeleniumDownloadStrategy.INTERNAL,
    "fetch": SeleniumDownloadStrategy.FETCH,
}

selenium_strats_dict: dict[str, SeleniumStrategy] = {
    "plain": SeleniumStrategy.PLAIN,
    "anymatch": SeleniumStrategy.ANYMATCH,
    "interactive": SeleniumStrategy.INTERACTIVE,
    "dedup": SeleniumStrategy.DEDUP,
}

verbosities_dict: dict[str, Verbosity] = {
    "error": Verbosity.ERROR,
    "warn": Verbosity.WARN,
    "info": Verbosity.INFO,
    "debug": Verbosity.DEBUG,
}

verbosities_display_dict: dict[Verbosity, str] = {
    Verbosity.ERROR: "[ERROR]: ",
    Verbosity.WARN:  " [WARN]: ",
    Verbosity.INFO:  " [INFO]: ",
    Verbosity.DEBUG: "[DEBUG]: ",
}
