from typing import TypeVar
from enum import Enum, IntEnum

# because for python, sys.argv[0] does not reflect what the user typed anyways,
# we just use this fixed value for --help etc.
SCRIPT_NAME = "scr"
VERSION = "0.12.0"

SCR_USER_AGENT = f"{SCRIPT_NAME}/{VERSION}"
FALLBACK_DOCUMENT_SCHEME = "https"
DEFAULT_TIMEOUT_SECONDS = 30
# cap for filenames deduced from urls to avoid a messs e.g. for data urls
URL_FILENAME_MAX_LEN = 256


# mimetype to use for selenium downloading to avoid triggering pdf viewers etc.
DUMMY_MIMETYPE = "application/zip"

DEFAULT_CPF = "{c}\\n"
DEFAULT_CWF = "{c}"
DEFAULT_CSF = "{fn}"
DEFAULT_ESCAPE_SEQUENCE = "<END>"


T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")


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
    ERROR = 7

    def accepted(self) -> bool:
        return self == InteractiveResult.ACCEPT or self == InteractiveResult.ACCEPT_CHAIN


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


class DocumentDuplication(Enum):
    ALLOWED = 0
    NONRECURSIVE = 1
    UNIQUE = 2


class DocumentType(Enum):
    URL = 1
    FILE = 2
    RFILE = 3
    STRING = 4
    RSTRING = 5

    def derived_link_type(self) -> 'DocumentType':
        return {
            DocumentType.URL: DocumentType.URL,
            DocumentType.FILE: DocumentType.FILE,
            DocumentType.RFILE: DocumentType.URL,
            DocumentType.STRING: DocumentType.FILE,
            DocumentType.RSTRING: DocumentType.URL,
        }[self]

    def non_r_type(self) -> 'DocumentType':
        if self == DocumentType.RFILE:
            return DocumentType.FILE
        if self == DocumentType.RSTRING:
            return DocumentType.STRING
        return self


document_type_dict: dict[str, DocumentType] = {
    "url": DocumentType.URL,
    "file": DocumentType.FILE,
    "rfile": DocumentType.RFILE,
    "str": DocumentType.STRING,
    "rstr": DocumentType.RSTRING
}

document_type_display_dict: dict[DocumentType, str] = {
    DocumentType.URL: "url",
    DocumentType.FILE: "file",
    DocumentType.RFILE: "rfile",
    DocumentType.STRING: "str",
    DocumentType.STRING: "rstr"
}

selenium_variants_dict: dict[str, SeleniumVariant] = {
    "disabled": SeleniumVariant.DISABLED,
    "tor": SeleniumVariant.TORBROWSER,
    "firefox": SeleniumVariant.FIREFOX,
    "chrome": SeleniumVariant.CHROME,
}

selenium_variants_display_dict: dict[SeleniumVariant, str] = {
    SeleniumVariant.DISABLED: "disabled",
    SeleniumVariant.TORBROWSER: "Tor Browser",
    SeleniumVariant.FIREFOX: "Firefox",
    SeleniumVariant.CHROME: "Chrome",
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

document_duplication_dict: dict[str, DocumentDuplication] = {
    "allowed": DocumentDuplication.ALLOWED,
    "nonrecursive": DocumentDuplication.NONRECURSIVE,
    "unique": DocumentDuplication.UNIQUE,
}
