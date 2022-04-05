#!/usr/bin/env python3
from abc import ABC, abstractmethod
import multiprocessing
from typing import Any, Callable, Iterable, Iterator, Optional, TypeVar, BinaryIO, TextIO, Union, cast
import urllib3.exceptions  # for selenium MaxRetryError
import mimetypes
import shutil
from io import BytesIO, SEEK_SET
import binascii
import threading
import shlex
import copy
from abc import abstractmethod
import lxml
import lxml.etree
import lxml.html
import requests
import sys
import xml.sax.saxutils
import select
import re
import datetime
import os
from string import Formatter
import readline
import urllib.parse
from http.cookiejar import MozillaCookieJar
from random_user_agent.user_agent import UserAgent
from tbselenium.tbdriver import TorBrowserDriver
import selenium
import selenium.webdriver.common.by
from selenium.webdriver.remote.webelement import WebElement as SeleniumWebElement
from selenium.webdriver.firefox.service import Service as SeleniumFirefoxService
from selenium.webdriver.chrome.service import Service as SeleniumChromeService
from selenium.webdriver.remote.webdriver import WebDriver as SeleniumWebDriver
from selenium.common.exceptions import WebDriverException as SeleniumWebDriverException
from selenium.common.exceptions import TimeoutException as SeleniumTimeoutException
from collections import deque, OrderedDict
from enum import Enum, IntEnum
import time
import tempfile
import itertools
import warnings
import urllib.request

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")


def prefixes(str: str) -> set[str]:
    return set(str[:i] for i in range(len(str), 0, -1))


def set_join(*args: Iterable[T]) -> set[T]:
    res: set[T] = set()
    for s in args:
        res.update(s)
    return res


YES_INDICATING_STRINGS = set_join(
    prefixes("yes"), prefixes("true"), ["1", "+"]
)
NO_INDICATING_STRINGS = set_join(prefixes("no"), prefixes("false"), ["0", "-"])
SKIP_INDICATING_STRINGS = prefixes("skip")
CHAIN_SKIP_INDICATING_STRINGS = prefixes("chainskip")
DOC_SKIP_INDICATING_STRINGS = prefixes("docskip")
DOC_SKIP_INDICATING_STRINGS = prefixes("edit")
INSPECT_INDICATING_STRINGS = prefixes("inspect")
ACCEPT_CHAIN_INDICATING_STRINGS = prefixes("acceptchain")
CHAIN_REGEX = re.compile("^[0-9\\-\\*\\^]*$")
DEFAULT_ESCAPE_SEQUENCE = "<END>"
DEFAULT_CPF = "{c}\\n"
DEFAULT_CWF = "{c}"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_TRUNCATION_LENGTH = 200
DEFAULT_RESPONSE_BUFFER_SIZE = 32768
DEFAULT_MAX_PRINT_BUFFER_CAPACITY = 2**20 * 100  # 100 MiB
# mimetype to use for selenium downloading to avoid triggering pdf viewers etc.
DUMMY_MIMETYPE = "application/zip"
FALLBACK_DOCUMENT_SCHEME = "https"
INTERNAL_USER_AGENT = "screp/0.2.0"

# very slow to initialize, so we do it lazily cached
RANDOM_USER_AGENT_INSTANCE: Optional[UserAgent] = None


class ScrepSetupError(Exception):
    pass


class ScrepFetchError(Exception):
    pass


class ScrepMatchError(Exception):
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


class SeleniumDownloadStrategy(Enum):
    EXTERNAL = 0
    INTERNAL = 1
    FETCH = 2


class SeleniumStrategy(Enum):
    DISABLED = 0
    FIRST = 1
    INTERACTIVE = 2
    DEDUP = 3


class Verbosity(IntEnum):
    ERROR = 1
    WARN = 2
    INFO = 3
    DEBUG = 4


class ContentFormat(Enum):
    STRING = 0,
    BYTES = 1,
    STREAM = 2,
    FILE = 3,
    TEMP_FILE = 4,
    UNNEEDED = 5,


class DocumentType(Enum):
    URL = 1
    FILE = 2
    RFILE = 3
    CONTENT_MATCH = 4

    def derived_type(self):
        if self == DocumentType.RFILE:
            return DocumentType.URL
        return self

    def url_handling_type(self):
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

selenium_download_strategies_dict: dict[str, SeleniumDownloadStrategy] = {
    "external": SeleniumDownloadStrategy.EXTERNAL,
    "internal": SeleniumDownloadStrategy.INTERNAL,
    "fetch": SeleniumDownloadStrategy.FETCH,
}

selenium_strats_dict: dict[str, SeleniumStrategy] = {
    "first": SeleniumStrategy.FIRST,
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


class MinimalInputStream(ABC):
    @abstractmethod
    def read(self, size: Optional[int]) -> bytes:
        pass

    @abstractmethod
    def close(self) -> None:
        pass

    @abstractmethod
    def __enter__(self) -> None:
        pass

    @abstractmethod
    def __exit__(self) -> None:
        pass


class ResponseStreamWrapper(MinimalInputStream):
    _bytes_buffer: bytearray
    _request_response: requests.models.Response
    _iterator: Iterator[bytes]
    _pos: int = 0

    def __init__(
        self, request_response: requests.models.Response,
        buffer_size: int = DEFAULT_RESPONSE_BUFFER_SIZE
    ) -> None:
        self._bytes_buffer = bytearray()
        self._request_response = request_response
        self._iterator = self._request_response.iter_content(buffer_size)

    def read(self, size: int = None) -> bytes:
        if size is None:
            goal_position = float("inf")
        else:
            goal_position = self._pos + size

        loaded_until = self._pos + len(self._bytes_buffer)
        while loaded_until < goal_position:
            try:
                buf = next(self._iterator)
            except StopIteration:
                goal_position = loaded_until
                break
            loaded_until += len(buf)
            if self._bytes_buffer:
                self._bytes_buffer.extend(buf)
            else:
                self._bytes_buffer = bytearray(buf)
        if loaded_until <= goal_position:
            self._pos = loaded_until
            res = self._bytes_buffer
            self._bytes_buffer = bytearray()
            return res
        assert type(goal_position) is int
        buf_pos = goal_position - self._pos
        self._pos = goal_position
        res = self._bytes_buffer[0:buf_pos]
        self._bytes_buffer = self._bytes_buffer[buf_pos:]
        return res

    def close(self) -> None:
        self._request_response.close()

    def __enter__(self) -> None:
        pass

    def __exit__(self) -> None:
        self.close()


class RegexMatch:
    xmatch: str
    rmatch: str
    unnamed_cgroups: list[str]
    named_cgroups: dict[str, str]

    def __init__(
        self, xmatch: str, rmatch: str,
        unnamed_cgroups: list[str] = [],
        named_cgroups: dict[str, str] = {}
    ) -> None:
        self.xmatch = xmatch
        self.rmatch = rmatch
        self.unnamed_cgroups = [
            x if x is not None else "" for x in unnamed_cgroups
        ]
        self.named_cgroups = {
            k: (v if v is not None else "")
            for (k, v) in named_cgroups.items()
        }

    def __key__(self) -> tuple[str, str]:
        # we only ever compare regex matches from the same match chain
        # therefore it is enough that the complete match is equivalent
        return (self.xmatch, self.rmatch)

    def __eq__(self, other) -> bool:
        return isinstance(other, self.__class__) and self.__key__() == other.__key__()

    def __hash__(self) -> int:
        return hash(self.__key__())

    def unnamed_group_list_to_dict(self, name_prefix: str) -> dict[str, str]:
        group_dict = {f"{name_prefix}0": self.rmatch}
        for i, g in enumerate(self.unnamed_cgroups):
            group_dict[f"{name_prefix}{i+1}"] = g
        return group_dict


class Document:
    document_type: DocumentType
    path: str
    path_parsed: urllib.parse.ParseResult
    encoding: Optional[str]
    forced_encoding: bool
    text: Optional[str]
    xml: Optional[lxml.html.HtmlElement]
    src_mc: Optional['MatchChain']
    regex_match: Optional[RegexMatch]
    dfmatch: Optional[str]

    def __init__(
        self, document_type: DocumentType, path: str,
        src_mc: Optional['MatchChain'],
        match_chains: list['MatchChain'] = None,
        expand_match_chains_above: Optional[int] = None,
        regex_match: Optional[RegexMatch] = None,
        path_parsed: Optional[urllib.parse.ParseResult] = None
    ) -> None:
        self.document_type = document_type
        self.path = path
        if path_parsed is not None:
            self.path_parsed = path_parsed
        else:
            self.path_parsed = urllib.parse.urlparse(path)
        self.encoding = None
        self.forced_encoding = False
        self.text = None
        self.xml = None
        self.src_mc = src_mc
        self.regex_match = regex_match
        self.dfmatch = None
        if not match_chains:
            self.match_chains = []
        else:
            self.match_chains = sorted(
                match_chains, key=lambda mc: mc.chain_id)
        self.expand_match_chains_above = expand_match_chains_above

    def __key__(self) -> tuple[DocumentType, str]:
        return (self.document_type, self.path)

    def __eq__(self, other) -> bool:
        return isinstance(self, other.__class__) and self.__key__() == other.__key__()

    def __hash__(self) -> int:
        return hash(self.__key__())


class ConfigDataClass:
    _config_slots_: list[str] = []
    _subconfig_slots_: list[str] = []
    _final_values_: set[str]
    _value_sources_: dict[str, str]

    def __init__(self, blank=False) -> None:
        self._final_values_ = set()
        self._value_sources_ = {}
        if not blank:
            return
        for k in self.__class__._config_slots_:
            self.__dict__[k] = None

    @staticmethod
    def _previous_annotations_as_config_slots(
        annotations: dict[str, Any],
        subconfig_slots: list[str]
    ) -> list[str]:
        subconfig_slots_dict = set(subconfig_slots + ["__annotations__"])
        return list(k for k in annotations.keys() if k not in subconfig_slots_dict)

    def apply_defaults(self, defaults):
        for cs in self.__class__._config_slots_:
            if cs in defaults.__dict__:
                def_val = defaults.__dict__[cs]
            else:
                def_val = defaults.__class__.__dict__[cs]
            if cs not in self.__dict__ or self.__dict__[cs] is None:
                self.__dict__[cs] = def_val
                vs = defaults._value_sources_.get(cs, None)
                if vs:
                    self._value_sources_[cs] = vs

        for scs in self.__class__._subconfig_slots_:
            self.__dict__[scs].apply_defaults(defaults.__dict__[scs])

    def follow_attrib_path(self, attrib_path: list[str]) -> tuple['ConfigDataClass', str]:
        assert(len(attrib_path))
        conf = self
        for attr in attrib_path[:-1]:
            assert attr in conf._subconfig_slots_
            conf = conf.__dict__[attr]
        attr = attrib_path[-1]
        assert attr in conf._config_slots_
        return conf, attr

    def resolve_attrib_path(self, attrib_path: list[str], transform: Optional[Callable[[Any], Any]] = None) -> tuple['ConfigDataClass', str]:
        conf, attr = self.follow_attrib_path(attrib_path)
        if attr in conf.__dict__:
            val = conf.__dict__[attr]
            if transform:
                val = transform(val)
                conf.__dict__[attr] = val
            return val
        val = conf.__class__.__dict__[attr]
        if transform:
            val = transform(val)
            conf.__class__.__dict__[attr] = val
        return val

    def has_custom_value(self, attrib_path: list[str]) -> bool:
        conf, attr = self.follow_attrib_path(attrib_path)
        return attr in conf._value_sources_

    def get_configuring_argument(self, attrib_path: list[str]) -> Optional[str]:
        conf, attr = self.follow_attrib_path(attrib_path)
        return conf._value_sources_.get(attr, None)

    def try_set_config_option(self, attrib_path: list[str], value: Any, arg: str) -> Optional[str]:
        conf, attr = self.follow_attrib_path(attrib_path)
        if attr in conf._final_values_:
            return conf._value_sources_[attr]
        conf._final_values_.add(attr)
        conf._value_sources_[attr] = arg
        conf.__dict__[attr] = value
        return None


class Locator(ConfigDataClass):
    name: str
    xpath: Optional[Union[str, lxml.etree.XPath]] = None
    regex: Optional[Union[str, re.Pattern]] = None
    format: Optional[str] = None
    multimatch: bool = True
    interactive: bool = False
    __annotations__: dict[str, type]

    _config_slots_: list[str] = (
        ConfigDataClass._previous_annotations_as_config_slots(
            __annotations__, []
        )
    )

    validated: bool = False

    def __init__(self, name: str, blank: bool = False) -> None:
        super().__init__(blank)
        self.name = name

    def compile_xpath(self, mc: 'MatchChain') -> None:
        if self.xpath is None:
            return
        try:
            xp = lxml.etree.XPath(self.xpath)
            xp.evaluate(lxml.html.HtmlElement("<div>test</div>"))
        except (lxml.etree.XPathSyntaxError, lxml.etree.XPathEvalError):
            # don't use the XPathSyntaxError message because they are spectacularily bad
            # e.g. XPath("/div/text(") -> XPathSyntaxError("Missing closing CURLY BRACE")
            raise ScrepSetupError(
                f"invalid xpath in {self.get_configuring_argument(['xpath'])}"
            )
        self.xpath = xp

    def gen_dummy_regex_match(self):
        if self.regex is None:
            if self.xpath is not None:
                return RegexMatch("", "")
            return None
        if type(self.regex) is not re.Pattern:
            return None
        capture_group_keys = list(self.regex.groupindex.keys())
        unnamed_regex_group_count = (
            self.regex.groups - len(capture_group_keys)
        )
        return RegexMatch(
            "", "",
            [""] * unnamed_regex_group_count,
            {k: "" for k in capture_group_keys}
        )

    def compile_regex(self, mc: 'MatchChain') -> None:
        if self.regex is None:
            return
        try:
            self.regex = re.compile(self.regex, re.DOTALL)
        except re.error as err:
            raise ScrepSetupError(
                f"invalid regex ({err.msg}) in {self.get_configuring_argument(['regex'])}"
            )

    def compile_format(self, mc: 'MatchChain') -> None:
        if self.format is None:
            return
        validate_format(self, ["format"],
                        mc.gen_dummy_content_match(), True, False)

    def setup(self, mc: 'MatchChain') -> None:
        self.xpath = empty_string_to_none(self.xpath)
        assert self.regex is None or type(self.regex) is str
        self.regex = empty_string_to_none(self.regex)
        self.format = empty_string_to_none(self.format)
        self.compile_xpath(mc)
        self.compile_regex(mc)
        self.compile_format(mc)
        self.validated = True

    def match_xpath(
        self, ctx: 'ScrepContext', src_xml: lxml.html.HtmlElement, path: str,
        default: tuple[
            list[str],
            Optional[list[lxml.html.HtmlElement]]
        ] = ([], []),
        return_xml: bool = False
    ) -> tuple[list[str], Optional[list[lxml.html.HtmlElement]]]:
        if self.xpath is None:
            return default
        try:
            xpath_matches = (
                cast(lxml.etree.XPath, self.xpath).evaluate(src_xml)
            )
        except lxml.etree.XPathEvalError as ex:
            raise ScrepMatchError(f"invalid xpath: '{self.xpath}'")
        except lxml.etree.LxmlError as ex:
            raise ScrepMatchError(
                f"failed to apply xpath '{self.xpath}' to {path}: "
                + f"{ex.__class__.__name__}:  {str(ex)}"
            )

        if not isinstance(xpath_matches, list):
            raise ScrepMatchError(f"invalid xpath: '{self.xpath}'")

        if len(xpath_matches) > 1 and not self.multimatch:
            xpath_matches = xpath_matches[:1]
        res = []
        res_xml = []
        for xm in xpath_matches:
            if type(xm) == lxml.etree._ElementUnicodeResult:
                string = str(xm)
                res.append(string)
                if return_xml:
                    try:
                        res_xml.append(lxml.html.fromstring(string))
                    except lxml.LxmlError:
                        pass
            else:
                try:
                    res.append(lxml.html.tostring(xm, encoding="unicode"))
                    if return_xml:
                        res_xml.append(xm)
                except (lxml.LxmlError, UnicodeEncodeError) as ex1:
                    raise ScrepMatchError(
                        f"{path}: xpath match encoding failed: {str(ex1)}"
                    )
        return res, res_xml

    def match_regex(
        self, xmatch: str, default: list[RegexMatch] = []
    ) -> list[RegexMatch]:
        if self.regex is None or xmatch is None:
            return default
        res = []
        for m in cast(re.Pattern, self.regex).finditer(xmatch):
            res.append(
                RegexMatch(xmatch, m.string, list(m.groups()), m.groupdict())
            )
            if not self.multimatch:
                break
        return res

    def apply_format(self, cm: 'ContentMatch', rm: Optional[RegexMatch]) -> str:
        if not self.format:
            assert rm is not None
            return rm.rmatch
        return self.format.format(**content_match_build_format_args(cm))

    def is_unset(self):
        return min([v is None for v in [self.xpath, self.regex, self.format]])


class MatchChain(ConfigDataClass):
    # config members
    ctx: 'ScrepContext'  # this is a config member so it is copied on apply_defaults
    content_escape_sequence: str = DEFAULT_ESCAPE_SEQUENCE
    cimin: int = 1
    cimax: Union[int, float] = float("inf")
    ci_continuous: bool = False
    content_save_format: Optional[str] = None
    content_print_format: Optional[str] = None
    content_write_format: Optional[str] = None
    content_forward_chains: list['MatchChain'] = []
    content_raw: bool = True
    content_input_encoding: str = "utf-8"
    content_forced_input_encoding: Optional[str] = None
    save_path_interactive: bool = False

    label_default_format: Optional[str] = None
    labels_inside_content: bool = False
    label_allow_missing: bool = False
    allow_slashes_in_labels: bool = False
    overwrite_files: bool = True

    dimin: int = 1
    dimax: Union[int, float] = float("inf")
    default_document_encoding: str = "utf-8"
    forced_document_encoding: Optional[str] = None

    default_document_scheme: str = FALLBACK_DOCUMENT_SCHEME
    prefer_parent_document_scheme: bool = True
    forced_document_scheme: Optional[str] = None

    selenium_strategy: SeleniumStrategy = SeleniumStrategy.FIRST
    selenium_download_strategy: SeleniumDownloadStrategy = SeleniumDownloadStrategy.EXTERNAL

    document_output_chains: list['MatchChain']
    __annotations__: dict[str, type]
    _config_slots_: list[str] = (
        ConfigDataClass._previous_annotations_as_config_slots(
            __annotations__, [])
    )

    # subconfig members
    content: Locator
    label: Locator
    document: Locator

    _subconfig_slots_ = ['content', 'label', 'document']

    # non config members
    chain_id: int
    di: int
    ci: int
    has_xpath_matching: bool = False
    has_label_matching: bool = False
    has_content_xpaths: bool = False
    has_document_matching: bool = False
    has_content_matching: bool = False
    has_interactive_matching: bool = False
    need_content_download: bool = False
    need_output_multipass: bool = False
    content_refs_write: int = 0
    content_refs_print: int = 0
    content_matches: list['ContentMatch']
    document_matches: list[Document]
    handled_content_matches: set['ContentMatch']
    handled_document_matches: set[Document]
    satisfied: bool = True
    labels_none_for_n: int = 0

    def __init__(self, ctx: 'ScrepContext', chain_id: int, blank: bool = False) -> None:
        super().__init__(blank)

        self.ctx = ctx
        self.chain_id = chain_id
        self.document_output_chains = []

        self.content = Locator("content", blank)
        self.label = Locator("label", blank)
        self.document = Locator("document", blank)

        self.content_matches = []
        self.document_matches = []
        self.handled_content_matches = set()
        self.handled_document_matches = set()

    def gen_dummy_content_match(self):
        dcm = ContentMatch(
            self.label.gen_dummy_regex_match(),
            self.content.gen_dummy_regex_match(),
            self,
            Document(
                DocumentType.FILE, "", None,
                regex_match=self.document.gen_dummy_regex_match()
            )
        )
        if dcm.content_regex_match or (
            self.content.format and self.content.validated
        ):
            dcm.cfmatch = ""
            dcm.cmatch = ""

        if dcm.label_regex_match or (
            self.label.format and self.label.validated
        ):
            dcm.lfmatch = ""
            dcm.lmatch = ""

        if dcm.doc.regex_match or (
            self.document.format and self.document.validated
        ):
            dcm.doc.dfmatch = ""
        if self.content.multimatch:
            dcm.ci = 0
        if self.has_document_matching:
            dcm.di = 0
        return dcm

    def accepts_content_matches(self) -> bool:
        return self.di <= self.dimax

    def need_document_matches(self, current_di_used) -> bool:
        return (
            self.has_document_matching
            and self.di <= (self.dimax - (1 if current_di_used else 0))
        )

    def need_content_matches(self) -> bool:
        assert self.ci is not None and self.di is not None
        return self.has_content_matching and self.ci <= self.cimax and self.di <= self.dimax

    def is_valid_label(self, label) -> bool:
        if self.allow_slashes_in_labels:
            return True
        if "/" in label or "\\" in label:
            return False
        return True


class ContentMatch:
    label_regex_match: Optional[RegexMatch] = None
    content_regex_match: Optional[RegexMatch] = None
    mc: MatchChain
    doc: Document

    # these are set once we accept the CM, not during it's creation
    ci: Optional[int] = None
    di: Optional[int] = None
    cfmatch: Optional[str] = None
    lfmatch: Optional[str] = None

    # these are potentially different from cfmatch/lfmatch due to interactive
    # matching or link normalization
    lmatch: Optional[str] = None
    cmatch: Optional[str] = None
    url_parsed: Optional[urllib.parse.ParseResult]

    def __init__(
        self,
        label_regex_match: Optional[RegexMatch],
        content_regex_match: Optional[RegexMatch],
        mc: MatchChain, doc: Document
    ):
        self.label_regex_match = label_regex_match
        self.content_regex_match = content_regex_match
        self.mc = mc
        self.doc = doc

    def __key__(self) -> Any:
        return (
            self.doc,
            self.label_regex_match.__key__() if self.label_regex_match else None,
            self.content_regex_match.__key__() if self.content_regex_match else None
        )

    def __eq__(x, y):
        return isinstance(y, x.__class__) and x.__key__() == y.__key__()

    def __hash__(self):
        return hash(self.__key__())


class ScrepContext(ConfigDataClass):
    # config members
    cookie_file: Optional[str] = None
    exit: bool = False
    selenium_variant: SeleniumVariant = SeleniumVariant.DISABLED
    tor_browser_dir: Optional[str] = None
    user_agent_random: Optional[bool] = False
    user_agent: Optional[str] = None
    verbosity: Verbosity = Verbosity.WARN
    documents_bfs: bool = False
    selenium_keep_alive: bool = False
    repl: bool = False
    request_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_download_threads: int = multiprocessing.cpu_count()

    selenium_log_path: str = os.path.devnull
    selenium_poll_frequency_secs: float = 0.3
    selenium_content_count_pad_length: int = 6
    downloads_temp_dir: Optional[str] = None
    download_tmp_index: int = 0

    # not really config, but recycled in repl mode
    dl_manager: Optional['DownloadManager'] = None
    cookie_jar: Optional[MozillaCookieJar] = None
    cookie_dict: dict[str, dict[str, dict[str, Any]]]
    selenium_driver: Optional[SeleniumWebDriver] = None
    __annotations__: dict[str, type]
    _config_slots_: list[str] = (
        ConfigDataClass._previous_annotations_as_config_slots(
            __annotations__, [])
    )

    # non config members
    match_chains: list[MatchChain]
    docs: deque[Document]
    reused_doc: Optional[Document] = None
    changed_selenium: bool = False
    defaults_mc: MatchChain
    origin_mc: MatchChain
    error_code: int = 0

    def __init__(self, blank=False):
        super().__init__(blank)
        self.cookie_dict = {}
        self.match_chains = []
        self.docs = deque()
        self.defaults_mc = MatchChain(self, None)
        self.origin_mc = MatchChain(self, None, blank=True)
        # turn ctx to none temporarily for origin so it can be deepcopied
        self.origin_mc.ctx = None


class OutputFormatter:
    _args_dict: dict[str, Any]
    _args_list: list[Any]
    _format_parts: list[tuple[str, Union[str, None],
                              Union[str, None], Union[str, None]]]
    _out_stream: Union[BinaryIO, 'PrintOutputStream']
    _found_stream: bool = False
    _input_buffer_sizes: int

    def __init__(
        self, format_str: str, cm: ContentMatch,
        out_stream: Union[BinaryIO, 'PrintOutputStream'],
        content: Union[str, bytes, MinimalInputStream, BinaryIO, None],
        input_buffer_sizes=DEFAULT_RESPONSE_BUFFER_SIZE
    ):
        self._args_dict = content_match_build_format_args(cm, content)
        self._args_list = []  # no positional args right now

        # we reverse these lists so we can take out elements using pop()
        self._format_parts = list(
            reversed(list(Formatter().parse(format_str)))
        )
        self._args_list = list(reversed(self._args_list))

        self._out_stream = out_stream
        self._found_stream = False
        self._input_buffer_sizes = input_buffer_sizes

    # returns True if it has not reached the end yet
    def advance(self, buffer: Optional[bytes] = None) -> bool:
        while True:
            if self._found_stream:
                if buffer is None:
                    return True
                if buffer:  # avoid length zero buffers which may cause errors
                    self._out_stream.write(buffer)
                if len(buffer) == self._input_buffer_sizes:
                    return True
                self._found_stream = False
                buffer = None
                if not len(self._format_parts):
                    break

            while self._format_parts:
                (text, key, format_args, b) = self._format_parts.pop()
                if text:
                    self._out_stream.write(text.encode("utf-8"))
                if key is not None:
                    if key == "":
                        val = self._args_list.pop()
                    else:
                        val = self._args_dict[key]
                    if type(val) is bytes:
                        self._out_stream.write(val)
                    elif type(val) in [str, int, float]:
                        self._out_stream.write(
                            format(val, format_args if format_args else "")
                            .encode("utf-8", errors="surrogateescape")
                        )
                    else:
                        assert key == "c"
                        self._found_stream = True
                        break
            if not self._found_stream:
                break

        assert buffer is None and not self._format_parts
        self._out_stream.flush()
        return False


class PrintOutputManager:
    printing_buffers: OrderedDict[int, list[bytes]]
    finished_queues: set[int]
    lock: threading.Lock
    size_blocked: threading.Condition
    size_limit: int
    dl_ids: int = 0
    active_id: int = 0
    main_thread_id: Optional[int] = None

    def __init__(self, max_buffer_size=DEFAULT_MAX_PRINT_BUFFER_CAPACITY):
        self.lock = threading.Lock()
        self.printing_buffers = OrderedDict()
        self.finished_queues = set()
        self.size_limit = max_buffer_size
        self.size_blocked = threading.Condition(self.lock)

    def reset(self):
        self.active_id = 0
        self.dl_ids = 0
        self.main_thread_id = self.request_print_access()

    def main_thread_done(self):
        if self.main_thread_id is not None:
            self.declare_done(self.main_thread_id)
            self.main_thread_id = None

    def print(self, id: int, buffer: bytes):
        is_active = False
        with self.lock:
            while True:
                if id == self.active_id:
                    is_active = True
                    stored_buffers = self.printing_buffers.pop(id, [])
                    self.size_limit += sum(
                        map(lambda b: len(b), stored_buffers)
                    )
                    break
                elif self.size_limit > len(buffer):
                    self.size_limit -= len(buffer)
                    self.printing_buffers[id].append(buffer)
                    break
                self.size_blocked.wait()
        if is_active:
            for b in stored_buffers:
                sys.stdout.buffer.write(b)
            sys.stdout.buffer.write(buffer)
            if(stored_buffers):
                self.size_blocked.notifyAll()
            return

    def request_print_access(self) -> int:
        with self.lock:
            id = self.dl_ids
            self.dl_ids += 1
            if id != self.active_id:
                self.printing_buffers[id] = []
        return id

    def declare_done(self, id: int):
        new_active_id = None
        buffers_to_print: list[list[bytes]] = []
        with self.lock:
            if self.active_id != id:
                self.finished_queues.add(id)
                return

            new_active_id = self.active_id + 1
            while new_active_id in self.finished_queues:
                self.finished_queues.remove(new_active_id)
                buffers_to_print.append(
                    self.printing_buffers.pop(new_active_id)
                )
                new_active_id += 1
        while True:
            for bl in buffers_to_print:
                for b in bl:
                    sys.stdout.buffer.write(b)
            # after we printed and reacquire the lock, the job
            # that we want to give the active_id token to
            # might have finished already, in which case we have to print him too
            buffers_to_print.clear()
            with self.lock:
                self.active_id = new_active_id
                if new_active_id not in self.finished_queues:
                    new_active_id = None
                    break
                while True:
                    self.finished_queues.remove(new_active_id)
                    buffers_to_print.append(
                        self.printing_buffers.pop(new_active_id)
                    )
                    new_active_id += 1
                    if new_active_id not in self.finished_queues:
                        break
            if new_active_id is None:
                break

    def flush(self, id: int):
        with self.lock:
            if not id != self.active_id:
                return
        sys.stdout.flush()


class PrintOutputStream:
    pom: PrintOutputManager
    id: int

    def __init__(self, pom: PrintOutputManager):
        self.pom = pom
        self.id = pom.request_print_access()

    def write(self, buffer: bytes) -> int:
        self.pom.print(self.id, buffer)
        return len(buffer)

    def flush(self):
        self.pom.flush(self.id)

    def close(self):
        self.pom.declare_done(self.id)


class DownloadJob:
    expected_size: int = 0
    fetched_size: int = 0
    save_file: Optional[BinaryIO] = None
    temp_file: Optional[BinaryIO] = None
    temp_file_path: Optional[str] = None
    multipass_file: Optional[BinaryIO] = None
    print_stream: Optional[PrintOutputStream] = None
    content_stream: Union[BinaryIO, MinimalInputStream, None] = None
    content: Union[str, bytes, BinaryIO, MinimalInputStream, None] = None
    content_format: ContentFormat

    cm: ContentMatch
    save_path: Optional[str]
    context: str
    output_formatters: list[OutputFormatter]

    def __init__(self, cm: ContentMatch, save_path: Optional[str]) -> None:
        self.cm = cm
        self.save_path = save_path
        self.context = (
            f"{truncate(self.cm.doc.path)}"
            + f"{get_ci_di_context(self.cm.mc, self.cm.di, self.cm.ci)}"
        )
        self.output_formatters = []

    def requires_download(self):
        return self.cm.mc.need_content_download

    def setup_print_stream(self, dm: 'DownloadManager'):
        if self.cm.mc.content_print_format is not None:
            self.print_stream = PrintOutputStream(dm.pom)

    def fetch_content(self) -> bool:
        path = cast(str, self.cm.cmatch)
        if self.cm.mc.content_raw:
            self.content = self.cm.cmatch
            self.content_format = ContentFormat.STRING
        else:
            path_parsed = cast(str, self.cm.url_parsed)
            if not self.cm.mc.need_content_download:
                self.content_format = ContentFormat.UNNEEDED
            else:
                if self.cm.mc.ctx.selenium_variant != SeleniumVariant.DISABLED:
                    self.content, self.content_format = selenium_download(
                        self.cm, self.save_path
                    )
                    if self.content is None:
                        return False
                else:
                    data = try_read_data_url(self.cm)
                    if data is not None:
                        self.content = data
                        self.content_format = ContentFormat.BYTES
                        return True
                    if self.cm.doc.document_type.derived_type() is DocumentType.FILE:
                        self.content = path
                        self.content_format = ContentFormat.FILE
                        return True
                    try:
                        self.content, _enc = requests_dl(
                            self.cm.mc.ctx, path,
                            cast(urllib.parse.ParseResult,
                                 self.cm.url_parsed),
                            stream=True
                        )
                        self.content_format = ContentFormat.STREAM
                    except ScrepFetchError as ex:
                        log(self.cm.mc.ctx, Verbosity.ERROR,
                            f"{self.context}: failed to download '{truncate(path)}': {str(ex)}")
                        return False
        return True

    def setup_save_file(self) -> bool:
        if not self.save_path:
            return True
        try:
            use_as_multipass = (
                self.cm.mc.need_output_multipass
                and self.multipass_file is None
                and self.cm.mc.content_write_format == DEFAULT_CWF
            )
            save_file = cast(BinaryIO, open(
                self.save_path,
                ("w" if self.cm.mc.overwrite_files else "x")
                + "b"
                + ("+" if use_as_multipass else "")
            ))
            if use_as_multipass:
                self.multipass_file = save_file
        except FileExistsError:
            log(self.cm.mc.ctx, Verbosity.ERROR,
                f"{self.context}: file already exists: {self.save_path}")
            return False
        except OSError as ex:
            log(
                self.cm.mc.ctx, Verbosity.ERROR,
                f"{self.context}: failed to write to file '{self.save_path}': {str(ex)}"
            )
            return False

        self.output_formatters.append(OutputFormatter(
            cast(str, self.cm.mc.content_write_format),
            self.cm, save_file, self.content
        ))
        return True

    def setup_content_file(self) -> bool:
        if self.content_format not in [ContentFormat.FILE, ContentFormat.TEMP_FILE]:
            return True
        assert type(self.content) is str
        try:
            self.content_stream = cast(BinaryIO, fetch_file(
                self.cm.mc.ctx, self.content, stream=True)
            )
        except ScrepFetchError as ex:
            log(self.cm.mc.ctx, Verbosity.ERROR,
                f"{self.context}: failed to open file '{truncate(self.content)}': {str(ex)}")
            self.aborted = True
            return False
        if self.content_format == ContentFormat.TEMP_FILE:
            self.temp_file_path = self.content
        self.content = self.content_stream
        if self.cm.mc.need_output_multipass:
            self.multipass_file = self.content_stream
        return True

    def setup_print_output(self) -> bool:
        if self.cm.mc.content_print_format is None:
            return True
        if self.print_stream is not None:
            stream: Union[PrintOutputStream, BinaryIO] = self.print_stream
        else:
            stream = sys.stdout.buffer
        self.output_formatters.append(OutputFormatter(
            self.cm.mc.content_print_format, self.cm,
            stream, self.content
        ))
        return True

    def download_content(self) -> bool:
        if not self.fetch_content():
            return False

        self.content_stream: Union[BinaryIO, MinimalInputStream, None] = (
            cast(Union[BinaryIO, MinimalInputStream], self.content)
            if self.content_format == ContentFormat.STREAM
            else None
        )
        try:
            if not self.setup_content_file():
                return False
            if not self.setup_save_file():
                return False

            if not self.setup_print_output():
                return False

            if self.content_stream is None:
                for of in self.output_formatters:
                    res = of.advance()
                    assert res == False
                return True

            if self.cm.mc.need_output_multipass and self.multipass_file is None:
                try:
                    self.temp_file_path, _filename = gen_dl_temp_name(
                        self.cm.mc.ctx, self.save_path)
                    self.temp_file = open(self.temp_file_path, "xb+")
                except IOError as ex:
                    return False
                self.multipass_file = self.temp_file

            if self.content_stream is not None:
                while True:
                    buf = self.content_stream.read(
                        DEFAULT_RESPONSE_BUFFER_SIZE
                    )
                    advance_output_formatters(self.output_formatters, buf)
                    if self.temp_file:
                        self.temp_file.write(buf)
                    if len(buf) < DEFAULT_RESPONSE_BUFFER_SIZE:
                        if self.content_stream is not self.multipass_file:
                            self.content_stream.close()
                            self.content_stream = None
                        break

            if self.multipass_file:
                while self.output_formatters:
                    self.multipass_file.seek(0)
                    while True:
                        buf = self.multipass_file.read(
                            DEFAULT_RESPONSE_BUFFER_SIZE)
                        advance_output_formatters(self.output_formatters, buf)
                        if len(buf) < DEFAULT_RESPONSE_BUFFER_SIZE:
                            break

        finally:
            if self.print_stream is not None:
                self.print_stream.close()
            if self.content_stream is not None:
                self.content_stream.close()
            if self.temp_file is not None:
                self.temp_file.close()
            if self.temp_file_path is not None:
                os.remove(self.temp_file_path)
            if self.save_file is not None:
                self.save_file.close()
        return True


class DownloadManager:
    ctx: ScrepContext
    threads: list[threading.Thread]
    max_threads: int
    pending_jobs: list[DownloadJob]
    running_jobs: list[DownloadJob]
    finished_jobs: list[DownloadJob]
    lock: threading.Lock
    queue_slots: threading.Semaphore
    all_threads_idle: threading.Condition
    pom: PrintOutputManager

    def __init__(self, ctx: ScrepContext, max_threads: int):
        self.ctx = ctx
        self.max_threads = max_threads
        self.pending_jobs = []
        self.running_jobs = []
        self.finished_jobs = []
        self.threads = []
        self.idle_threads: int = 0
        self.lock = threading.Lock()
        self.pending_job_count = threading.Semaphore(value=0)
        self.pom = PrintOutputManager()
        self.all_threads_idle = threading.Condition(self.lock)

    def submit(self, dj: DownloadJob):
        log(self.ctx, Verbosity.DEBUG,
            f"enqueuing download for {dj.cm.cmatch}"
            )
        dj.setup_print_stream(self)
        t = None
        with self.lock:
            self.pending_jobs.append(dj)
            thread_count = len(self.threads)
            if len(self.threads) < self.max_threads and self.idle_threads == 0:
                t = threading.Thread(target=self.run_worker,
                                     args=(thread_count + 1,))
                self.threads.append(t)
        self.pending_job_count.release()
        if t:
            log(self.ctx, Verbosity.DEBUG,
                f"starting downloading thread #{thread_count + 1}")
            t.start()

    def run_worker(self, id: int):
        try:
            while True:
                job = None
                with self.lock:
                    self.idle_threads += 1
                    if (self.idle_threads == len(self.threads)):
                        self.all_threads_idle.notifyAll()
                self.pending_job_count.acquire()
                with self.lock:
                    if not self.pending_jobs:
                        # the semaphore only lets us through without present jobs
                        # if the process wants to terminate
                        return
                    job = self.pending_jobs.pop(0)
                    self.idle_threads -= 1
                log(self.ctx, Verbosity.DEBUG,
                    f"thread #{id}: started downloading {job.cm.cmatch}"
                    )
                if job.download_content():
                    log(
                        self.ctx, Verbosity.DEBUG,
                        f"thread #{id}: finished downloading {job.cm.cmatch}"
                    )
                else:
                    log(
                        self.ctx, Verbosity.DEBUG,
                        f"thread #{id}: failed to download {job.cm.cmatch}"
                    )
        except KeyboardInterrupt:
            sys.exit(1)
        except BrokenPipeError:
            abort_on_broken_pipe()

    def wait_until_jobs_done(self):
        with self.lock:
            while True:
                launched_threads = len(self.threads)
                idle_threads = self.idle_threads
                if launched_threads == idle_threads:
                    return
                self.all_threads_idle.wait()

    def terminate(self, cancel_running: bool = False):
        if cancel_running:
            with self.lock:
                self.pending_jobs.clear()
        self.pending_job_count.release(self.max_threads)
        for t in self.threads:
            t.join()


def abort_on_broken_pipe():
    # Python flushes standard streams on exit; redirect remaining output
    # to devnull to avoid another BrokenPipeError at shutdown
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    sys.exit(1)


def empty_string_to_none(string: Optional[str]) -> Optional[str]:
    if string == "":
        return None
    return string


def dict_update_unless_none(current: dict[K, Any], updates: dict[K, Any]) -> None:
    current.update({
        k: v for k, v in updates.items() if v is not None
    })


def content_match_build_format_args(
    cm: ContentMatch, content: Union[str, bytes, MinimalInputStream, BinaryIO, None] = None
) -> dict[str, Any]:
    args_dict = {
        "cenc": cm.doc.encoding,
        "cesc": cm.mc.content_escape_sequence,
        "dl":   cm.doc.path,
    }
    potential_regex_matches = [
        ("d", cm.doc.regex_match),
        ("l", cm.label_regex_match),
        ("c", cm.content_regex_match)
    ]
    # remove None regex matches (and type cast this to make mypy happy)
    regex_matches = list(map(lambda p: cast(tuple[str, RegexMatch], p),
                             filter(
        lambda rm: rm[1] is not None, potential_regex_matches)
    ))
    for p, rm in regex_matches:
        args_dict.update({
            f"{p}x": rm.xmatch,
            f"{p}r": rm.rmatch,
        })

    dict_update_unless_none(args_dict, {
        "cf": cm.cfmatch,
        "cm": cm.cmatch,
        "lf": cm.lfmatch,
        "l": cm.lmatch,
        "df": cm.doc.dfmatch,
        "d": cm.doc.path,
        "di": cm.di,
        "ci": cm.ci,
        "c": content,
        "chain": cm.mc.chain_id,
    })

    # apply the unnamed groups first in case somebody overwrote it with a named group
    for p, rm in regex_matches:
        args_dict.update(rm.unnamed_group_list_to_dict(f"{p}g"))

    # finally apply the named groups
    for p, rm in regex_matches:
        args_dict.update(rm.named_cgroups)

    return args_dict


def log_raw(verbosity: Verbosity, msg: str) -> None:
    sys.stderr.write(verbosities_display_dict[verbosity] + msg + "\n")


BSE_U_REGEX_MATCH = re.compile("[0-9A-Fa-f]{4}")


def parse_bse_u(match: re.Match) -> str:
    code = match[3]
    if not BSE_U_REGEX_MATCH.match(code):
        raise ValueError(f"invalid escape code \\u{code}")
    code = (b"\\u" + code.encode("ascii")).decode("unicodeescape")
    return "".join(map(lambda x: x if x else "", [match[1], match[2], code]))


BSE_X_REGEX_MATCH = re.compile("[0-9A-Fa-f]{2}")


def parse_bse_x(match: re.Match) -> str:
    code = match[3]
    if not BSE_X_REGEX_MATCH.match(code):
        raise ValueError(f"invalid escape code \\x{code}")
    code = (b"\\udc" + code.encode("ascii")).decode("unicode_escape")
    return "".join(map(lambda x: x if x else "", [match[1], match[2], code]))


def parse_bse_o(match: re.Match) -> str:
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
            raise ValueError(f"unterminated escape sequence '\\'")
        raise ValueError(f"invalid escape code \\{code}")
    return "".join(map(lambda x: x if x else "", [match[1], match[2], res]))


BACKSLASHESCAPE_PATTERNS = [
    (re.compile(r"(^|[^\\])(\\\\)*\\u(.{0,4})"), parse_bse_u),
    (re.compile(r"(^|[^\\])(\\\\)*\\x(.{0,2})"), parse_bse_x),
    (re.compile(
        "(^|[^\\\\])(\\\\\\\\)*\\\\([rntfb\\'\\\"\\\\]|$)"), parse_bse_o),
]


def unescape_string(txt: str):
    for regex, parser in BACKSLASHESCAPE_PATTERNS:
        txt = regex.sub(parser, txt)
    return txt


def log(ctx: ScrepContext, verbosity: Verbosity, msg: str) -> None:
    if verbosity == Verbosity.ERROR:
        ctx.error_code = 1
    if ctx.verbosity >= verbosity:
        log_raw(verbosity, msg)


def help(err: bool = False) -> None:
    global DEFAULT_CPF
    global DEFAULT_CWF
    text = f"""{sys.argv[0]} [OPTIONS]
    Extract content from urls or files by specifying content matching chains
    (xpath -> regex -> python format string).

    Content to Write out:
        cx=<xpath>           xpath for content matching
        cr=<regex>           regex for content matching
        cf=<format string>   content format string (args: <cr capture groups>, xmatch, rmatch, di, ci)
        cmm=<bool>           allow multiple content matches in one document instead of picking the first (defaults to true)
        cimin=<number>       initial content index, each successful match gets one index
        cimax=<number>       max content index, matching stops here
        cicont=<bool>        don't reset the content index for each document
        csf=<format string>  save content to file at the path resulting from the format string, empty to enable
        cwf=<format string>  format to write to file. defaults to \"{DEFAULT_CWF}\"
        cpf=<format string>  print the result of this format string for each content, empty to disable
                             defaults to \"{DEFAULT_CPF}\" if cpf, csf and cfc are unspecified
        cfc=<chain spec>     forward content match as a virtual document
        cff=<format string>  format of the virtual document forwarded to the cfc chains. defaults to \"{DEFAULT_CWF}\"
        csin<bool>           give a promt to edit the save path for a file
        cin=<bool>           give a prompt to ignore a potential content match
        cl=<bool>            treat content match as a link to the actual content
        cesc=<string>        escape sequence to terminate content in cin mode, defaults to \"{DEFAULT_ESCAPE_SEQUENCE}\"
        cenc=<encoding>      default encoding to assume that content is in
        cfenc=<encoding>     encoding to always assume that content is in, even if http(s) says differently

    Labels to give each matched content (mostly useful for the filename in csf):
        lx=<xpath>          xpath for label matching
        lr=<regex>          regex for label matching
        lf=<format string>  label format string
        lic=<bool>          match for the label within the content match instead of the hole document
        las=<bool>          allow slashes in labels
        lmm=<bool>          allow multiple label matches in one document instead of picking the first (for all content matches)
        lam=<bool>          allow missing label (default is to skip content if no label is found)
        lfd=<format string> default label format string to use if there's no match
        lin=<bool>          give a prompt to edit the generated label

    Further documents to scan referenced in already found ones:
        dx=<xpath>          xpath for document matching
        dr=<regex>          regex for document matching
        df=<format string>  document format string
        dimin=<number>      initial document index, each successful match gets one index
        dimax=<number>      max document index, matching stops here
        dmm=<bool>           allow multiple document matches in one document instead of picking the first
        din=<bool>          give a prompt to ignore a potential document match
        denc=<encoding>     default document encoding to use for following documents, default is utf-8
        dfenc=<encoding>    force document encoding for following documents, even if http(s) says differently
        dsch=<scheme>       default scheme for urls derived from following documents, defaults to "https"
        dpsch=<bool>        use the parent documents scheme if available, defaults to true unless dsch is specified
        dfsch=<scheme>      force this scheme for urls derived from following documents
        doc=<chain spec>    chains that matched documents should apply to, default is the same chain

    Initial Documents:
        url=<url>           fetch a document from a url, derived document matches are (relative) urls
        file=<path>         fetch a document from a file, derived documents matches are (relative) file pathes
        rfile=<path>        fetch a document from a file, derived documents matches are urls

    Other:
        selstrat=<strategy> matching strategy for selenium (default: first, values: first, interactive, deduplicate)
        seldl=<dl strategy> download strategy for selenium (default: external, values: external, internal, fetch)
        owf=<bool>          allow to overwrite existing files, defaults to true

    Format Args:
        Named arguments for <format string> arguments.
        Some only become available later in the pipeline (e.g. {{cm}} is not available inside cf).

        {{cx}}                content xpath match
        {{cr}}                content regex match, equal to {{cx}} if cr is unspecified
        <cr capture groups> the named regex capture groups (?P<name>...) from cr are available as {{name}},
                            the unnamed ones (...) as {{cg<unnamed capture group number>}}
        {{cf}}                content after applying cf
        {{cm}}                final content match after link normalization (cl) and user interaction (cin)

        {{lx}}                label xpath match
        {{lr}}                label regex match, equal to {{lx}} if lr is unspecified
        <lr capture groups> the named regex capture groups (?P<name>...) from cr are available as {{name}},
                            the unnamed ones (...) as {{lg<unnamed capture group number>}}
        {{lf}}                label after applying lf
        {{l}}                 final label after user interaction (lin)

        {{dx}}                document link xpath match
        {{dr}}                document link regex match, equal to {{dx}} if dr is unspecified
        <dr capture groups> the named regex capture groups (?P<name>...) from dr are available as {{name}},
                            the unnamed ones (...) as {{dg<unnamed capture group number>}}
        {{df}}                document link after applying df
        {{d}}                final document link after user interaction (din)

        {{di}}                document index
        {{ci}}                content index
        {{dl}}                document link (even for df, this still refers to the parent document)
        {{cenc}}              content encoding, deduced while respecting cenc and cfenc
        {{cesc}}              escape sequence for separating content, can be overwritten using cesc
        {{chain}}             id of the match chain that generated this content

        {{c}}                 content, downloaded from cm in case of cl, otherwise equal to cm

    Chain Syntax:
        Any option above can restrict the matching chains is should apply to using opt<chainspec>=<value>.
        Use "-" for ranges, "," for multiple specifications, and "^" to except the following chains.
        Examples:
            lf1,3-5=foo     sets "lf" to "foo" for chains 1, 3, 4 and 5.
            lf2-^4=bar      sets "lf" to "bar" for all chains larger than or equal to 2, except chain 4

    Global Options:
        timeout=<seconds>   seconds before a web request timeouts (default {DEFAULT_TIMEOUT_SECONDS})
        bfs=<bool>          traverse the matched documents in breadth first order instead of depth first
        v=<verbosity>       output verbosity levels (default: warn, values: info, warn, error)
        ua=<string>         user agent to pass in the html header for url GETs
        uar=<bool>          use a rangom user agent
        selkeep=<bool>      keep selenium instance alive after the command finished
        cookiefile=<path>   path to a netscape cookie file. cookies are passed along for url GETs
        sel=<browser>       use selenium to load urls into an interactive browser session
                            (default: disabled, values: tor, chrome, firefox, disabled)
        tbdir=<path>        root directory of the tor browser installation, implies sel=tor
                            (default: environment variable TOR_BROWSER_DIR)
        mt=<int>            maximum threads for background downloads, 0 to disable. defaults to cpu core count.
        repl=<bool>         accept commands in a read eval print loop
        exit=<bool>         exit the repl (with the result of the current command)
        """.strip()
    if err:
        sys.stderr.write(text + "\n")
        sys.exit(1)

    else:
        print(text)


def add_cwd_to_path() -> str:
    cwd = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
    os.environ["PATH"] += ":" + cwd
    return cwd


def truncate(
    text: str,
    max_len: int = DEFAULT_TRUNCATION_LENGTH,
    trailer: str = "..."
) -> str:
    if len(text) > max_len:
        assert(max_len > len(trailer))
        return text[0: max_len - len(trailer)] + trailer
    return text


def selenium_build_firefox_options(
    ctx: ScrepContext
) -> selenium.webdriver.FirefoxOptions:
    ff_options = selenium.webdriver.FirefoxOptions()
    if ctx.user_agent is not None:
        ff_options.set_preference("general.useragent.override", ctx.user_agent)
        if ctx.selenium_variant == SeleniumVariant.TORBROWSER:
            # otherwise the user agent is not applied
            ff_options.set_preference("privacy.resistFingerprinting", False)

    prefs = {}
    # setup download dir and disable save path popup
    if ctx.downloads_temp_dir is not None:
        mimetypes.init()
        save_mimetypes = ";".join(set(mimetypes.types_map.values()))
        prefs.update({
            "browser.download.dir": ctx.downloads_temp_dir,
            "browser.download.useDownloadDir": True,
            "browser.download.folderList": 2,
            "browser.download.manager.showWhenStarting": False,
            "browser.helperApps.neverAsk.saveToDisk": save_mimetypes,
            "browser.helperApps.showOpenOptionForViewableInternally": False,
            "pdfjs.disabled": True,
        })
    # make sure new tabs don't open new windows
    prefs.update({
        "browser.link.open_newwindow": 3,
        "browser.link.open_newwindow.restriction": 0,
        "browser.link.open_newwindow.override.external": -1,
    })

    # apply prefs
    for pk, pv in prefs.items():
        ff_options.set_preference(pk, pv)
    return ff_options


def setup_selenium_tor(ctx: ScrepContext) -> None:
    # use bundled geckodriver if available
    cwd = add_cwd_to_path()
    if ctx.tor_browser_dir is None:
        tb_env_var = "TOR_BROWSER_DIR"
        if tb_env_var in os.environ:
            ctx.tor_browser_dir = os.environ[tb_env_var]
        else:
            raise ScrepSetupError(f"no tbdir specified, check --help")
    try:
        ctx.selenium_driver = TorBrowserDriver(
            ctx.tor_browser_dir, tbb_logfile_path=ctx.selenium_log_path,
            options=selenium_build_firefox_options(ctx)
        )

    except SeleniumWebDriverException as ex:
        raise ScrepSetupError(f"failed to start tor browser: {str(ex)}")
    os.chdir(cwd)  # restore cwd that is changed by tor for some reason


def setup_selenium_firefox(ctx: ScrepContext) -> None:
    # use bundled geckodriver if available
    add_cwd_to_path()
    try:
        ctx.selenium_driver = selenium.webdriver.Firefox(
            options=selenium_build_firefox_options(ctx),
            service=SeleniumFirefoxService(
                log_path=ctx.selenium_log_path),  # type: ignore
        )
    except SeleniumWebDriverException as ex:
        raise ScrepSetupError(f"failed to start geckodriver: {str(ex)}")


def setup_selenium_chrome(ctx: ScrepContext) -> None:
    # allow usage of bundled chromedriver
    add_cwd_to_path()
    options = selenium.webdriver.ChromeOptions()
    options.add_argument("--incognito")
    if ctx.user_agent != None:
        options.add_argument(f"user-agent={ctx.user_agent}")

    if ctx.downloads_temp_dir is not None:
        prefs = {
            "download.default_directory": ctx.downloads_temp_dir,
            "download.prompt_for_download": False,
            "profile.default_content_setting_values.automatic_downloads": 1,
        }
        options.add_experimental_option("prefs", prefs)

    try:
        ctx.selenium_driver = selenium.webdriver.Chrome(
            options=options,
            service=SeleniumChromeService(
                log_path=ctx.selenium_log_path)  # type: ignore
        )
    except SeleniumWebDriverException as ex:
        raise ScrepSetupError(f"failed to start chromedriver: {str(ex)}")


def selenium_add_cookies_through_get(ctx: ScrepContext) -> None:
    # ctx.selenium_driver.set_page_load_timeout(0.01)
    assert ctx.selenium_driver is not None
    for domain, cookies in ctx.cookie_dict.items():
        try:
            ctx.selenium_driver.get(f"https://{domain}")
        except SeleniumTimeoutException:
            raise ScrepSetupError(
                "Failed to apply cookies for https://{domain}: page failed to load")
        for c in cookies.values():
            ctx.selenium_driver.add_cookie(c)


def new_start(*args, **kwargs):
    def preexec_function():
        # signal.signal(signal.SIGINT, signal.SIG_IGN) # this one didn't worked for me
        os.setpgrp()
    default_Popen = subprocess.Popen
    subprocess.Popen = functools.partial(
        subprocess.Popen, preexec_fn=preexec_function)
    try:
        new_start.default_start(*args, **kwargs)
    finally:
        subprocess.Popen = default_Popen


new_start.default_start = selenium.webdriver.common.service.Service.start
selenium.webdriver.common.service.Service.start = new_start


def setup_selenium(ctx: ScrepContext) -> None:
    if ctx.selenium_variant == SeleniumVariant.TORBROWSER:
        setup_selenium_tor(ctx)
    elif ctx.selenium_variant == SeleniumVariant.CHROME:
        setup_selenium_chrome(ctx)
    elif ctx.selenium_variant == SeleniumVariant.FIREFOX:
        setup_selenium_firefox(ctx)
    else:
        assert False
    assert ctx.selenium_driver is not None
    if ctx.user_agent is None:
        ctx.user_agent = ctx.selenium_driver.execute_script(
            "return navigator.userAgent;")

    ctx.selenium_driver.set_page_load_timeout(ctx.request_timeout_seconds)
    if ctx.cookie_jar:
        # todo: implement something more clever for this, at least for chrome:
        # https://stackoverflow.com/questions/63220248/how-to-preload-cookies-before-first-request-with-python3-selenium-chrome-webdri
        selenium_add_cookies_through_get(ctx)


def get_format_string_keys(fmt_string) -> list[str]:
    return [f for (_, f, _, _) in Formatter().parse(fmt_string) if f is not None]


def format_string_uses_arg(fmt_string, arg_pos, arg_name) -> int:
    if fmt_string is None:
        return 0
    fmt_args = get_format_string_keys(fmt_string)
    count = 0
    if arg_name is not None:
        count += fmt_args.count(arg_name)
    if arg_pos is not None and fmt_args.count("") > arg_pos:
        count += 1
    return count


def validate_format(conf: ConfigDataClass, attrib_path: list[str], dummy_cm: ContentMatch, unescape: bool, has_content: bool = False) -> None:
    try:
        known_keys = content_match_build_format_args(
            dummy_cm, "" if has_content else None)
        unnamed_key_count = 0
        fmt_keys = get_format_string_keys(
            conf.resolve_attrib_path(
                attrib_path, unescape_string if unescape else None)
        )
        named_arg_count = 0
        for k in fmt_keys:
            if k == "":
                named_arg_count += 1
                if named_arg_count > unnamed_key_count:
                    raise ScrepSetupError(
                        f"exceeded number of ordered keys in {conf.get_configuring_argument(attrib_path)}"
                    )
            elif k not in known_keys:
                raise ScrepSetupError(
                    f"unavailable key '{{{k}}}' in {conf.get_configuring_argument(attrib_path)}"
                )
    except (re.error, ValueError) as ex:
        raise ScrepSetupError(
            f"{str(ex)} in {conf.get_configuring_argument(attrib_path)}"
        )

# we need ctx because mc.ctx is stil None before we apply_defaults


def setup_match_chain(mc: MatchChain, ctx: ScrepContext) -> None:
    mc.apply_defaults(ctx.defaults_mc)

    locators = [mc.content, mc.label, mc.document]
    for l in locators:
        l.setup(mc)

    if mc.dimin > mc.dimax:
        raise ScrepSetupError(f"dimin can't exceed dimax")
    if mc.cimin > mc.cimax:
        raise ScrepSetupError(f"cimin can't exceed cimax")
    mc.ci = mc.cimin
    mc.di = mc.dimin

    if mc.content_write_format and not mc.content_save_format:
        raise ScrepSetupError(
            f"match chain {mc.chain_id}: cannot specify cwf without csf"
        )

    if not mc.document_output_chains:
        mc.document_output_chains = [mc]

    if mc.save_path_interactive and not mc.content_save_format:
        mc.content_save_format = ""

    mc.has_xpath_matching = any(l.xpath is not None for l in locators)
    mc.has_label_matching = mc.label.xpath is not None or mc.label.regex is not None
    mc.has_content_xpaths = mc.labels_inside_content is not None and mc.label.xpath is not None
    mc.has_document_matching = mc.has_document_matching or mc.document.xpath is not None or mc.document.regex is not None or mc.document.format is not None
    mc.has_content_matching = mc.has_content_matching or mc.content.xpath is not None or mc.content.regex is not None or mc.content.format is not None
    mc.has_interactive_matching = mc.label.interactive or mc.content.interactive

    if mc.content_print_format or mc.content_save_format:
        mc.has_content_matching = True

    if mc.has_content_matching and not mc.content_print_format and not mc.content_save_format:
        mc.content_print_format = DEFAULT_CPF

    dummy_cm = mc.gen_dummy_content_match()
    if mc.content_print_format:
        validate_format(mc, ["content_print_format"], dummy_cm, True, True)

    if mc.content_save_format:
        validate_format(mc, ["content_save_format"], dummy_cm, True, False)
        if mc.content_write_format is None:
            mc.content_write_format = DEFAULT_CWF
        else:
            validate_format(mc, ["content_write_format"], dummy_cm, True, True)

    if not mc.has_label_matching:
        mc.label_allow_missing = True
        if mc.labels_inside_content:
            raise ScrepSetupError(
                f"match chain {mc.chain_id}: cannot specify lic without lx or lr"
            )

    if mc.label_default_format is None and mc.label_allow_missing:
        form = "dl_"
        # if max was not set it is 'inf' which has length 3 which is a fine default
        didigits = max(len(str(mc.dimin)), len(str(mc.dimax)))
        cidigits = max(len(str(mc.dimin)), len(str(mc.dimax)))
        if mc.ci_continuous:
            form += f"{{ci:0{cidigits}}}"
        elif mc.content.multimatch:
            if mc.has_document_matching:
                form += f"{{di:0{didigits}}}_{{ci:0{cidigits}}}"
            else:
                form += f"{{ci:0{cidigits}}}"

        elif mc.has_document_matching:
            form += f"{{di:0{didigits}}}"

        mc.label_default_format = form
    mc.content_refs_print = format_string_uses_arg(
        mc.content_print_format, None, "c"
    )
    mc.content_refs_write = format_string_uses_arg(
        mc.content_write_format, None, "c"
    )
    mc.need_content_download = (
        mc.content_refs_print + mc.content_refs_write) > 0
    mc.need_output_multipass = (
        mc.content_refs_print > 1
        or mc.content_refs_write > 1
    )
    if not mc.has_content_matching and not mc.has_document_matching:
        if not (mc.chain_id == 0 and mc.ctx.repl):
            raise ScrepSetupError(
                f"match chain {mc.chain_id} is unused, it has neither document nor content matching"
            )


def load_selenium_cookies(ctx: ScrepContext) -> dict[str, dict[str, dict[str, Any]]]:
    assert ctx.selenium_driver is not None
    cookies: list[dict[str, Any]] = ctx.selenium_driver.get_cookies()
    cookie_dict: dict[str, dict[str, dict[str, Any]]] = {}
    for ck in cookies:
        if cast(str, ck["domain"]) not in cookie_dict:
            cookie_dict[ck["domain"]] = {}
        cookie_dict[ck["domain"]][ck["name"]] = ck
    return cookie_dict


def load_cookie_jar(ctx: ScrepContext) -> None:
    if ctx.cookie_file is None:
        return
    try:
        ctx.cookie_jar = MozillaCookieJar()
        ctx.cookie_jar.load(
            os.path.expanduser(ctx.cookie_file),
            ignore_discard=True,
            ignore_expires=True
        )
    # this exception handling is really ugly but this is how this library
    # does it internally
    except OSError:
        raise
    except Exception as ex:
        raise ScrepSetupError(f"failed to read cookie file: {str(ex)}")
    for cookie in ctx.cookie_jar:
        ck: dict[str, Any] = {
            'domain': cookie.domain,
            'name': cookie.name,
            'value': cookie.value,
            'secure': cookie.secure
        }
        if cookie.expires:
            ck['expiry'] = cookie.expires
        if cookie.path_specified:
            ck['path'] = cookie.path
        if cookie.domain in ctx.cookie_dict:
            ctx.cookie_dict[cookie.domain][cookie.name] = ck
        else:
            ctx.cookie_dict[cookie.domain] = {cookie.name: ck}


def setup(ctx: ScrepContext, for_repl: bool = False) -> None:
    global DEFAULT_CPF
    ctx.apply_defaults(ScrepContext())

    if ctx.tor_browser_dir:
        if ctx.selenium_variant == SeleniumVariant.DISABLED:
            ctx.selenium_variant = SeleniumVariant.TORBROWSER
    load_cookie_jar(ctx)

    if ctx.user_agent is not None and ctx.user_agent_random:
        raise ScrepSetupError(f"the options ua and uar are incompatible")
    elif ctx.user_agent_random:
        global RANDOM_USER_AGENT_INSTANCE
        if RANDOM_USER_AGENT_INSTANCE is None:
            RANDOM_USER_AGENT_INSTANCE = UserAgent()
        ctx.user_agent = RANDOM_USER_AGENT_INSTANCE.get_random_user_agent()
    elif ctx.user_agent is None and ctx.selenium_variant == SeleniumVariant.DISABLED:
        ctx.user_agent = INTERNAL_USER_AGENT

    # if no chains are specified, use the origin chain as chain 0
    if not ctx.match_chains:
        ctx.match_chains = [ctx.origin_mc]
        ctx.origin_mc.chain_id = 0

    for d in ctx.docs:
        if d.expand_match_chains_above is not None:
            d.match_chains.extend(
                ctx.match_chains[d.expand_match_chains_above:])

    for mc in ctx.match_chains:
        setup_match_chain(mc, ctx)

    if len(ctx.docs) == 0:
        report = True
        if ctx.repl:
            if not any(mc.has_content_matching or mc.has_document_matching for mc in ctx.match_chains):
                report = False
        if report:
            raise ScrepSetupError("must specify at least one url or (r)file")

    if not ctx.downloads_temp_dir:
        have_internal_dls = any(
            mc.selenium_download_strategy == SeleniumDownloadStrategy.INTERNAL
            for mc in ctx.match_chains
        )

        have_dls_to_temp = any(
            mc.need_output_multipass for mc in ctx.match_chains
        )

        if (have_dls_to_temp or have_internal_dls):
            ctx.downloads_temp_dir = tempfile.mkdtemp(
                prefix="screp_downloads_"
            )

    if ctx.selenium_variant == SeleniumVariant.DISABLED:
        for mc in ctx.match_chains:
            mc.selenium_strategy = SeleniumStrategy.DISABLED
    elif ctx.selenium_driver is None:
        setup_selenium(ctx)

    if ctx.dl_manager is None and ctx.max_download_threads != 0:
        ctx.dl_manager = DownloadManager(ctx, ctx.max_download_threads)
    if ctx.dl_manager is not None:
        ctx.dl_manager.pom.reset()


def parse_prompt_option(
    val: str, options: list[tuple[T, set[str]]],
    default: Optional[T] = None
) -> Optional[T]:
    val = val.strip().lower()
    if val == "":
        return default
    for opt, matchings in options:
        if val in matchings:
            return opt
    return None


def parse_bool_string(val: str, default: Optional[bool] = None) -> Optional[bool]:
    return parse_prompt_option(val, [(True, YES_INDICATING_STRINGS), (False, NO_INDICATING_STRINGS)], default)


def get_representative_indicating_string(indicating_strings: set[str]) -> str:
    candidates = sorted(indicating_strings)
    i = 0
    while i + 1 < len(candidates):
        if begins(candidates[i+1], candidates[i]):
            del i
        else:
            i += 1
    return sorted(candidates, key=lambda c: len(c))[-1]


def prompt(prompt_text: str, options: list[tuple[T, set[str]]], default: Optional[T] = None) -> T:
    assert len(options) > 1
    while True:
        res = parse_prompt_option(input(prompt_text), options, default)
        if res is None:
            option_names = [get_representative_indicating_string(
                matchings) for _opt, matchings in options]
            print("please answer with " +
                  ", ".join(option_names[:-1]) + " or " + option_names[-1])
            continue
        return res


def prompt_yes_no(prompt_text: str, default: Optional[bool] = None) -> Optional[bool]:
    return prompt(prompt_text, [(True, YES_INDICATING_STRINGS), (False, NO_INDICATING_STRINGS)], default)


def selenium_get_url(ctx: ScrepContext) -> Optional[str]:
    assert ctx.selenium_driver is not None
    try:
        return ctx.selenium_driver.current_url
    except (SeleniumWebDriverException, urllib3.exceptions.MaxRetryError) as e:
        report_selenium_died(ctx)
        return None


def selenium_has_died(ctx: ScrepContext) -> bool:
    assert ctx.selenium_driver is not None
    try:
        # throws an exception if the session died
        return not len(ctx.selenium_driver.window_handles) > 0
    except (SeleniumWebDriverException, urllib3.exceptions.MaxRetryError) as e:
        return True


def gen_dl_temp_name(
    ctx: ScrepContext, final_filepath: Optional[str]
) -> tuple[str, str]:
    assert ctx.downloads_temp_dir is not None
    dl_index = ctx.download_tmp_index
    ctx.download_tmp_index += 1
    tmp_filename = f"dl{dl_index}"
    if final_filepath is not None:
        tmp_filename += "_" + os.path.basename(final_filepath)
    else:
        tmp_filename += ".bin"
    tmp_path = os.path.join(ctx.downloads_temp_dir, tmp_filename)
    return tmp_path, tmp_filename


def selenium_download_from_local_file(
    cm: ContentMatch, filepath: Optional[str]
) -> tuple[Optional[str], ContentFormat]:
    doc_url = selenium_get_url(cm.mc.ctx)
    if doc_url is None:
        return None, ContentFormat.FILE
    return cast(str, cm.cmatch), ContentFormat.FILE


def selenium_download_external(
    cm: ContentMatch, filepath: Optional[str]
) -> tuple[Optional[MinimalInputStream], ContentFormat]:
    proxies = None
    path = cast(str, cm.cmatch)
    if cm.mc.ctx.selenium_variant == SeleniumVariant.TORBROWSER:
        tbdriver = cast(TorBrowserDriver, cm.mc.ctx.selenium_driver)
        proxies = {
            "http": f"socks5h://localhost:{tbdriver.socks_port}",
            "https": f"socks5h://localhost:{tbdriver.socks_port}",
            "data": None
        }
    try:
        stream, _enc = requests_dl(
            cm.mc.ctx, path, cast(urllib.parse.ParseResult, cm.url_parsed),
            load_selenium_cookies(cm.mc.ctx),
            proxies=proxies, stream=True
        )
        return cast(MinimalInputStream, stream), ContentFormat.STREAM
    except ScrepFetchError as ex:
        log(
            cm.mc.ctx, Verbosity.ERROR,
            f"{truncate(cm.doc.path)}{get_ci_di_context(cm.mc, cm.di, cm.ci)}: "
            + f"failed to download '{truncate(path)}': {str(ex)}"
        )
        return None, ContentFormat.STREAM


def selenium_download_internal(
    cm: ContentMatch, filepath: Optional[str]
) -> tuple[Optional[str], ContentFormat]:
    doc_url_str = selenium_get_url(cm.mc.ctx)
    if doc_url_str is None:
        return None, ContentFormat.TEMP_FILE
    doc_url = urllib.parse.urlparse(doc_url_str)

    if doc_url.netloc != cast(urllib.parse.ParseResult, cm.url_parsed).netloc:
        log(
            cm.mc.ctx, Verbosity.ERROR,
            f"{cm.cmatch}{get_ci_di_context(cm.mc, cm.di, cm.ci)}: "
            + f"failed to download: seldl=internal does not work across origins"
        )
        return None, ContentFormat.TEMP_FILE

    tmp_path, tmp_filename = gen_dl_temp_name(cm.mc.ctx, filepath)
    script_source = """
        const url = arguments[0];
        const filename = arguments[1];
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    """
    try:
        cast(SeleniumWebDriver, cm.mc.ctx.selenium_driver).execute_script(
            script_source, cm.cmatch, tmp_filename
        )
    except SeleniumWebDriverException as ex:
        if selenium_has_died(cm.mc.ctx):
            report_selenium_died(cm.mc.ctx)
        else:
            log(
                cm.mc.ctx, Verbosity.ERROR,
                f"{cm.cmatch}{get_ci_di_context(cm.mc, cm.di, cm.ci)}: "
                + f"selenium download failed: {str(ex)}"
            )
        return None, ContentFormat.TEMP_FILE
    i = 0
    while True:
        if os.path.exists(tmp_path):
            time.sleep(0.1)
            break
        if i < 10:
            time.sleep(0.01)
        else:
            time.sleep(0.1)
            if i > 15:
                i = 10
                if selenium_has_died(cm.mc.ctx):
                    return None, ContentFormat.TEMP_FILE

        i += 1
    return tmp_path, ContentFormat.TEMP_FILE


def selenium_download_fetch(
    cm: ContentMatch, filepath: Optional[str]
) -> tuple[Optional[bytes], ContentFormat]:
    script_source = """
        const url = arguments[0];
        return (async () => {
            return await fetch(url, {
                method: 'GET',
            })
            .then(response => response.blob())
            .then(blob => new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.readAsDataURL(blob);
                reader.onload = () => resolve(reader.result.substr(reader.result.indexOf(',') + 1));
                reader.onerror = error => reject(error);
            }))
            .then(result => {
                return {
                    "ok": result
                };
            })
            .catch(ex => {
                return {
                    "error": ex.message
                };
            });
        })();
    """
    err = None
    driver = cast(SeleniumWebDriver, cm.mc.ctx.selenium_driver)
    try:
        doc_url = driver.current_url
        res = driver.execute_script(
            script_source, cm.cmatch
        )
    except SeleniumWebDriverException as ex:
        if selenium_has_died(cm.mc.ctx):
            report_selenium_died(cm.mc.ctx)
            return None, ContentFormat.BYTES
        err = str(ex)
    if "error" in res:
        err = res["error"]
    if err is not None:
        cors_warn = ""
        if urllib.parse.urlparse(doc_url).netloc != urllib.parse.urlparse(cm.cmatch).netloc:
            cors_warn = " (potential CORS issue)"
        log(
            cm.mc.ctx, Verbosity.ERROR,
            f"{truncate(cm.doc.path)}{get_ci_di_context(cm.mc, cm.di, cm.ci)}: "
            + f"selenium download of '{cm.cmatch}' failed{cors_warn}: {err}"
        )
        return None, ContentFormat.BYTES
    return binascii.a2b_base64(res["ok"]), ContentFormat.BYTES


def selenium_download(
    cm: ContentMatch, filepath: Optional[str] = None
) -> tuple[Union[str, bytes, MinimalInputStream, None], ContentFormat]:
    if (
        cm.doc.document_type == DocumentType.FILE
        and cast(urllib.parse.ParseResult, cm.url_parsed).scheme in ["", "file"]
    ):
        return selenium_download_from_local_file(cm, filepath)

    if cm.mc.selenium_download_strategy == SeleniumDownloadStrategy.EXTERNAL:
        return selenium_download_external(cm, filepath)

    if cm.mc.selenium_download_strategy == SeleniumDownloadStrategy.INTERNAL:
        return selenium_download_internal(cm, filepath)

    assert cm.mc.selenium_download_strategy == SeleniumDownloadStrategy.FETCH

    return selenium_download_fetch(cm, filepath)


def fetch_file(ctx: ScrepContext, path: str, stream: bool = False) -> Union[bytes, BinaryIO]:
    try:
        f = open(path, "rb")
        if stream:
            return f
        try:
            return f.read()
        finally:
            f.close()
    except FileNotFoundError as ex:
        raise ScrepFetchError("no such file or directory") from ex
    except IOError as ex:
        raise ScrepFetchError(truncate(str(ex))) from ex


def try_read_data_url(cm: ContentMatch) -> Optional[bytes]:
    assert cm.url_parsed is not None
    if cm.url_parsed.scheme == "data":
        res = urllib.request.urlopen(
            cast(str, cm.cmatch),
            timeout=cm.mc.ctx.request_timeout_seconds
        )
        try:
            data = res.read()
        finally:
            res.close()
        return data
    return None


def requests_dl(
    ctx: ScrepContext, path: str, path_parsed: urllib.parse.ParseResult,
    cookie_dict: Optional[dict[str, dict[str, dict[str, Any]]]] = None,
    proxies=None, stream=False
) -> tuple[Union[MinimalInputStream, bytes, None], Optional[str]]:

    hostname = path_parsed.hostname if path_parsed.hostname else ""
    if cookie_dict is None:
        cookie_dict = ctx.cookie_dict
    cookies = {
        name: ck["value"]
        for name, ck in cookie_dict.get(hostname, {}).items()
    }
    headers = {'User-Agent': ctx.user_agent}
    try:
        res = requests.get(
            path, cookies=cookies, headers=headers, allow_redirects=True,
            proxies=proxies, timeout=ctx.request_timeout_seconds, stream=stream
        )
        if stream:
            return ResponseStreamWrapper(res), res.encoding
        data = res.content
        encoding = res.encoding
        res.close()
        return data, encoding

    except requests.exceptions.InvalidURL as ex:
        raise ScrepFetchError("invalid url")
    except requests.exceptions.ConnectionError as ex:
        raise ScrepFetchError("connection failed")
    except requests.exceptions.ConnectTimeout as ex:
        raise ScrepFetchError("connection timeout")
    except requests.exceptions.RequestException as ex:
        raise ScrepFetchError(truncate(str(ex)))


def report_selenium_died(ctx: ScrepContext, is_err: bool = True) -> None:
    log(ctx, Verbosity.ERROR if is_err else Verbosity.WARN,
        "the selenium instance was closed unexpectedly")


def report_selenium_error(ctx: ScrepContext, ex: Exception) -> None:
    log(ctx, Verbosity.ERROR, f"critical selenium error: {str(ex)}")


def advance_output_formatters(output_formatters: list[OutputFormatter], buf: Optional[bytes]) -> None:
    i = 0
    while i < len(output_formatters):
        if output_formatters[i].advance(buf):
            i += 1
        else:
            del output_formatters[i]


def selenium_get_full_page_source(ctx: ScrepContext):
    drv = cast(SeleniumWebDriver, ctx.selenium_driver)
    text = drv.page_source
    page_xml: lxml.html.HtmlElement = lxml.html.fromstring(text)
    iframes_xml_all_sources: list[lxml.html.HtmlElement] = page_xml.xpath(
        "//iframe")
    if not iframes_xml_all_sources:
        return text, page_xml
    iframes_by_source: dict[str, lxml.html.HtmlElement] = {}
    for iframe in iframes_xml_all_sources:
        iframe_src = iframe.attrib["src"]
        iframe_src_escaped = xml.sax.saxutils.escape(iframe_src)
        if iframe_src_escaped in iframes_by_source:
            iframes_by_source[iframe_src_escaped].append(iframe)
        else:
            iframes_by_source[iframe_src_escaped] = [iframe]

    for iframe_src_escaped, iframes_xml in iframes_by_source.items():
        iframes_sel = drv.find_elements(
            by=selenium.webdriver.common.by.By.XPATH, value=f"//iframe[@src='{iframe_src_escaped}']"
        )
        len_sel = len(iframes_sel)
        len_xml = len(iframes_xml)
        if len_sel != len_xml:
            log(ctx, Verbosity.WARN,
                "iframe count diverged for iframe source '{iframe_src_escaped}'")
        for i in range(0, min(len_sel, len_xml)):
            try:
                drv.switch_to.frame(iframes_sel[i])
                loaded_iframe_text = drv.page_source
            finally:
                drv.switch_to.default_content()
            loaded_iframe_xml = lxml.html.fromstring(loaded_iframe_text)
            iframes_xml[i].append(loaded_iframe_xml)

    return lxml.html.tostring(page_xml), page_xml


def fetch_doc(ctx: ScrepContext, doc: Document) -> None:
    if ctx.selenium_variant != SeleniumVariant.DISABLED:
        if doc is not ctx.reused_doc or ctx.changed_selenium:
            selpath = doc.path
            if doc.document_type in [DocumentType.FILE, DocumentType.RFILE]:
                selpath = "file:" + os.path.realpath(selpath)
            try:
                cast(SeleniumWebDriver, ctx.selenium_driver).get(selpath)
            except SeleniumTimeoutException:
                ScrepFetchError("selenium timeout")

        decide_document_encoding(ctx, doc)
        doc.text, doc.xml = selenium_get_full_page_source(ctx)
        return
    if doc is ctx.reused_doc:
        ctx.reused_doc = None
        if doc.text and not ctx.changed_selenium:
            return
    if doc.document_type in [DocumentType.FILE, DocumentType.RFILE]:
        data = cast(bytes, fetch_file(ctx, doc.path, stream=False))
        encoding = decide_document_encoding(ctx, doc)
        doc.text = data.decode(encoding, errors="surrogateescape")
        return
    assert doc.document_type == DocumentType.URL

    data, encoding = cast(tuple[bytes, str], requests_dl(
        ctx, doc.path, doc.path_parsed
    ))
    if data is None:
        raise ScrepFetchError("empty response")
    doc.encoding = encoding
    encoding = decide_document_encoding(ctx, doc)
    doc.text = data.decode(encoding, errors="surrogateescape")
    return


def gen_final_content_format(format_str: str, cm: ContentMatch) -> bytes:
    with BytesIO(b"") as buf:
        of = OutputFormatter(format_str, cm, buf, None)
        while of.advance():
            pass
        buf.seek(0)
        return buf.read()


def normalize_link(
    ctx: ScrepContext, mc: Optional[MatchChain], src_doc: Document,
    doc_path: Optional[str], link: str, link_parsed: urllib.parse.ParseResult
) -> tuple[str, urllib.parse.ParseResult]:
    doc_url_parsed = urllib.parse.urlparse(doc_path) if doc_path else None
    if src_doc.document_type == DocumentType.FILE:
        if not link_parsed.scheme:
            if not os.path.isabs(link):
                if doc_url_parsed is not None:
                    base = doc_url_parsed.path
                    if ctx.selenium_variant != SeleniumVariant.DISABLED:
                        # attempt to preserve short, relative paths were possible
                        if os.path.realpath(doc_url_parsed.path) == os.path.realpath(src_doc.path):
                            base = src_doc.path
                else:
                    base = src_doc.path
                link = os.path.normpath(
                    os.path.join(os.path.dirname(base), link))
                return link, urllib.parse.urlparse(link)
        return link, link_parsed
    if doc_url_parsed and link_parsed.netloc == "" and src_doc.document_type == DocumentType.URL:
        link_parsed = link_parsed._replace(netloc=doc_url_parsed.netloc)

    # for urls like 'google.com' urllib makes this a path instead of a netloc
    if link_parsed.netloc == "" and not doc_url_parsed and link_parsed.scheme == "" and link_parsed.path != "" and link[0] not in [".", "/"]:
        link_parsed = link_parsed._replace(path="", netloc=link_parsed.path)
    if (mc and mc.forced_document_scheme):
        link_parsed = link_parsed._replace(scheme=mc.forced_document_scheme)
    elif link_parsed.scheme == "":
        if (mc and mc.prefer_parent_document_scheme) and doc_url_parsed and doc_url_parsed.scheme not in ["", "file"]:
            scheme = doc_url_parsed.scheme
        elif mc:
            scheme = mc.default_document_scheme
        else:
            scheme = FALLBACK_DOCUMENT_SCHEME
        link_parsed = link_parsed._replace(scheme=scheme)
    return link_parsed.geturl(), link_parsed


def get_ci_di_context(mc: MatchChain, di: Optional[int], ci: Optional[int]) -> str:
    if mc.has_document_matching:
        if mc.content.multimatch:
            di_ci_context = f" (di={di}, ci={ci})"
        else:
            di_ci_context = f" (di={di})"
    elif mc.content.multimatch:
        di_ci_context = f" (ci={ci})"
    else:
        di_ci_context = f""
    return di_ci_context


def handle_content_match(cm: ContentMatch) -> InteractiveResult:
    cm.di = cm.mc.di
    cm.ci = cm.mc.ci
    cm.cfmatch = cm.mc.content.apply_format(cm, cm.content_regex_match)
    cm.cmatch = cm.cfmatch

    if cm.label_regex_match is None:
        cm.lfmatch = cast(str, cm.mc.label_default_format).format(
            **content_match_build_format_args(cm)
        )
    else:
        cm.lfmatch = cm.mc.label.apply_format(
            cm, cm.label_regex_match
        )
    cm.lmatch = cm.lfmatch

    di_ci_context = get_ci_di_context(cm.mc, cm.di, cm.ci)

    if cm.mc.has_label_matching:
        label_context = f' (label "{cm.lmatch}")'
    else:
        label_context = ""

    while True:
        if not cm.mc.content_raw:
            cm.url_parsed = urllib.parse.urlparse(cm.cmatch)
            if cm.mc.ctx.selenium_variant == SeleniumVariant.DISABLED:
                doc_url = cm.doc.path
            else:
                sel_url = selenium_get_url(cm.mc.ctx)
                if sel_url is None:
                    return InteractiveResult.ERROR
                doc_url = sel_url

            cm.cmatch, cm.url_parsed = normalize_link(
                cm.mc.ctx, cm.mc, cm.doc, doc_url, cm.cmatch, cm.url_parsed
            )
        content_type = "content match" if cm.mc.content_raw else "content link"
        if cm.mc.content.interactive:
            prompt_options = [
                (InteractiveResult.ACCEPT, YES_INDICATING_STRINGS),
                (InteractiveResult.REJECT, NO_INDICATING_STRINGS),
                (InteractiveResult.EDIT, DOC_SKIP_INDICATING_STRINGS),
                (InteractiveResult.SKIP_CHAIN, CHAIN_SKIP_INDICATING_STRINGS),
                (InteractiveResult.SKIP_DOC, DOC_SKIP_INDICATING_STRINGS)
            ]
            if cm.mc.content_raw:
                prompt_options.append(
                    (InteractiveResult.INSPECT, INSPECT_INDICATING_STRINGS))
                inspect_opt_str = "/inspect"
                prompt_msg = f'accept {content_type} from "{cm.doc.path}"{di_ci_context}{label_context}'
            else:
                inspect_opt_str = ""
                prompt_msg = f'"{cm.doc.path}"{di_ci_context}{label_context}: accept {content_type} "{cm.cmatch}"'

            res = prompt(
                f'{prompt_msg} [Yes/no/edit{inspect_opt_str}/chainskip/docskip]? ',
                prompt_options,
                InteractiveResult.ACCEPT
            )
            if res is InteractiveResult.ACCEPT:
                break
            if res == InteractiveResult.INSPECT:
                print(
                    f'content for "{cm.doc.path}"{label_context}:\n' + cm.cmatch)
                continue
            if res is not InteractiveResult.EDIT:
                return res
            if not cm.mc.content_raw:
                cm.cmatch = input(f"enter new {content_type}:\n")
            else:
                print(
                    f'enter new {content_type} (terminate with a newline followed by the string "{cm.mc.content_escape_sequence}"):\n')
                cm.cmatch = ""
                while True:
                    cm.cmatch += input() + "\n"
                    i = cm.cmatch.find(
                        "\n" + cm.mc.content_escape_sequence)
                    if i != -1:
                        cm.cmatch = cm.cmatch[:i]
                        break
        break
    if cm.mc.label.interactive:
        while True:
            if not cm.mc.is_valid_label(cm.lmatch):
                log(cm.mc.ctx, Verbosity.WARN,
                    f'"{cm.doc.path}": labels cannot contain a slash ("{cm.lmatch}")')
            else:
                prompt_options = [
                    (InteractiveResult.ACCEPT, YES_INDICATING_STRINGS),
                    (InteractiveResult.REJECT, NO_INDICATING_STRINGS),
                    (InteractiveResult.EDIT, DOC_SKIP_INDICATING_STRINGS),
                    (InteractiveResult.SKIP_CHAIN, CHAIN_SKIP_INDICATING_STRINGS),
                    (InteractiveResult.SKIP_DOC, DOC_SKIP_INDICATING_STRINGS)
                ]
                if cm.mc.content_raw:
                    prompt_options.append(
                        (InteractiveResult.INSPECT, INSPECT_INDICATING_STRINGS))
                    inspect_opt_str = "/inspect"
                    prompt_msg = f'"{cm.doc.path}"{di_ci_context}: accept content label "{cm.lmatch}"'
                else:
                    inspect_opt_str = ""
                    prompt_msg = f'"{cm.doc.path}": {content_type} {cm.cmatch}{di_ci_context}: accept content label "{cm.lmatch}"'

                res = prompt(
                    f'{prompt_msg} [Yes/no/edit/{inspect_opt_str}/chainskip/docskip]? ',
                    prompt_options,
                    InteractiveResult.ACCEPT
                )
                if res == InteractiveResult.ACCEPT:
                    break
                if res == InteractiveResult.INSPECT:
                    print(
                        f'"{cm.doc.path}": {content_type} for "{cm.lmatch}":\n' + cm.cmatch)
                    continue
                if res != InteractiveResult.EDIT:
                    return res
            cm.lmatch = input("enter new label: ")

    save_path = None
    if cm.mc.content_save_format:
        if not cm.mc.is_valid_label(cm.lmatch):
            log(cm.mc.ctx, Verbosity.WARN,
                f"matched label '{cm.lmatch}' would contain a slash, skipping this content from: {cm.doc.path}")
        save_path_bytes = gen_final_content_format(
            cm.mc.content_save_format, cm)
        try:
            save_path = save_path_bytes.decode(
                "utf-8", errors="surrogateescape")
        except UnicodeDecodeError:
            log(cm.mc.ctx, Verbosity.ERROR,
                f"{cm.doc.path}{di_ci_context}: generated save path is not valid utf-8")
            save_path = None
        while True:
            if save_path and not os.path.exists(os.path.dirname(os.path.abspath(save_path))):
                log(cm.mc.ctx, Verbosity.ERROR,
                    f"{cm.doc.path}{di_ci_context}: directory of generated save path does not exist")
                save_path = None
            if not save_path and not cm.mc.save_path_interactive:
                return InteractiveResult.ERROR
            if not cm.mc.save_path_interactive:
                break
            if save_path:
                res = prompt(
                    f'{cm.doc.path}{di_ci_context}: accept save path "{save_path}" [Yes/no/edit/chainskip/docskip]? ',
                    [
                        (InteractiveResult.ACCEPT, YES_INDICATING_STRINGS),
                        (InteractiveResult.REJECT, NO_INDICATING_STRINGS),
                        (InteractiveResult.EDIT, DOC_SKIP_INDICATING_STRINGS),
                        (InteractiveResult.SKIP_CHAIN,
                         CHAIN_SKIP_INDICATING_STRINGS),
                        (InteractiveResult.SKIP_DOC, DOC_SKIP_INDICATING_STRINGS)
                    ],
                    InteractiveResult.ACCEPT
                )
                if res == InteractiveResult.ACCEPT:
                    break
                if res != InteractiveResult.EDIT:
                    return res
            save_path = input("enter new save path: ")
    cm.mc.ci += 1
    job = DownloadJob(cm, save_path)
    if cm.mc.ctx.dl_manager is not None and job.requires_download():
        cm.mc.ctx.dl_manager.submit(job)
    else:
        log(cm.mc.ctx, Verbosity.DEBUG,
            f"choosing synchronous download for {job.cm.cmatch}"
            )
        job.download_content()

    return InteractiveResult.ACCEPT


def handle_document_match(mc: MatchChain, doc: Document) -> InteractiveResult:
    if not mc.document.interactive:
        return InteractiveResult.ACCEPT
    while True:
        res = prompt(
            f'accept matched document "{doc.path}" [Yes/no/edit]? ',
            [
                (InteractiveResult.ACCEPT, YES_INDICATING_STRINGS),
                (InteractiveResult.REJECT, NO_INDICATING_STRINGS),
                (InteractiveResult.EDIT, DOC_SKIP_INDICATING_STRINGS),
                (InteractiveResult.SKIP_CHAIN, CHAIN_SKIP_INDICATING_STRINGS),
                (InteractiveResult.SKIP_DOC, DOC_SKIP_INDICATING_STRINGS)
            ],
            InteractiveResult.ACCEPT
        )
        if res == InteractiveResult.EDIT:
            doc.path = input("enter new document: ")
            continue
        return res


def gen_content_matches(mc: MatchChain, doc: Document, last_doc_path: str) -> tuple[list[ContentMatch], int]:
    content_matches = []
    text = cast(str, doc.text)
    xmatches, xmatches_xml = mc.content.match_xpath(
        mc.ctx, doc.xml, doc.path,
        ([text], [doc.xml]), mc.has_content_xpaths
    )
    label_regex_matches = []
    if mc.has_label_matching and not mc.labels_inside_content:
        lxmatches, _xml = mc.label.match_xpath(
            mc.ctx, doc.xml, doc.path, ([text], []))
        for lxmatch in lxmatches:
            label_regex_matches.extend(mc.label.match_regex(
                text, [RegexMatch(lxmatch, lxmatch)]
            ))
    match_index = 0
    labels_none_for_n = 0
    for xmatch in xmatches:
        content_regex_matches = mc.content.match_regex(
            xmatch, [RegexMatch(xmatch, xmatch)]
        )
        if mc.labels_inside_content and mc.label.xpath:
            xmatch_xml = (
                cast(list[lxml.html.HtmlElement], xmatches_xml)[match_index]
                if mc.has_content_xpaths
                else None
            )
            label_regex_matches = []
            lxmatches, _xml = mc.label.match_xpath(
                mc.ctx, xmatch_xml, doc.path, ([text], []))
            for lxmatch in lxmatches:
                label_regex_matches.extend(mc.label.match_regex(
                    text, [RegexMatch(lxmatch, lxmatch)])
                )
            if len(label_regex_matches) == 0:
                if not mc.label_allow_missing:
                    labels_none_for_n += len(content_regex_matches)
                    continue
                lrm = None
            else:
                lrm = label_regex_matches[0]

        for crm in content_regex_matches:
            if mc.labels_inside_content:
                if not mc.label.xpath:
                    label_regex_matches = mc.label.match_regex(
                        crm.rmatch, [RegexMatch(crm.rmatch, crm.rmatch)]
                    )
                    if len(label_regex_matches) == 0:
                        if not mc.label_allow_missing:
                            labels_none_for_n += 1
                            continue
                        lrm = None
                    else:
                        lrm = label_regex_matches[0]
            else:
                if not mc.label.multimatch and len(label_regex_matches) > 0:
                    lrm = label_regex_matches[0]
                elif match_index < len(label_regex_matches):
                    lrm = label_regex_matches[match_index]
                elif not mc.label_allow_missing:
                    labels_none_for_n += 1
                    continue
                else:
                    lrm = None

            content_matches.append(ContentMatch(lrm, crm, mc, doc))
        match_index += 1
    return content_matches, labels_none_for_n


def gen_document_matches(mc: MatchChain, doc: Document, last_doc_path: str) -> list[Document]:
    document_matches = []
    base_dir = os.path.dirname(doc.path)
    xmatches, _xml = mc.document.match_xpath(
        mc.ctx, doc.xml, doc.path, ([cast(str, doc.text)], [])
    )
    for xmatch in xmatches:
        rmatches = mc.document.match_regex(
            xmatch, [RegexMatch(xmatch, xmatch)]
        )
        for rm in rmatches:
            ndoc = Document(
                doc.document_type.derived_type(),
                "",
                mc,
                mc.document_output_chains,
                None,
                rm
            )
            ndoc.dfmatch = mc.document.apply_format(
                ContentMatch(None, None, mc, ndoc), rm
            )
            ndoc.path, ndoc.path_parsed = normalize_link(
                mc.ctx, mc, doc, last_doc_path, ndoc.dfmatch,
                urllib.parse.urlparse(ndoc.dfmatch)
            )
            document_matches.append(ndoc)

    return document_matches


def make_padding(ctx: ScrepContext, count_number: int) -> tuple[str, str]:
    content_count_pad_len = (
        ctx.selenium_content_count_pad_length
        - min(len(str(count_number)), ctx.selenium_content_count_pad_length)
    )
    rpad = int(content_count_pad_len / 2)
    lpad = content_count_pad_len - rpad
    return lpad * " ", rpad * " "


def handle_interactive_chains(
    ctx: ScrepContext,
    interactive_chains: list[MatchChain],
    doc: Document,
    last_doc_path: str,
    try_number: int, last_msg: str
) -> tuple[Optional[InteractiveResult], str]:
    content_count = 0
    docs_count = 0
    labels_none_for_n = 0
    have_document_matching = False
    have_content_matching = False
    for mc in interactive_chains:
        content_count += len(mc.content_matches)
        docs_count += len(mc.document_matches)
        labels_none_for_n += mc.labels_none_for_n
        if mc.need_document_matches(True):
            have_document_matching = True
        if mc.need_content_matches():
            have_content_matching = True

    msg = f"{last_doc_path}: use page with potentially"
    if have_content_matching:
        lpad, rpad = make_padding(ctx, content_count)
        msg += f'{lpad}< {content_count} >{rpad} content'
        if content_count != 1:
            msg += "s"
        else:
            msg += " "

    if labels_none_for_n != 0:
        msg += f" (missing {labels_none_for_n} labels)"
    if have_document_matching:
        lpad, rpad = make_padding(mc.ctx, docs_count)
        if have_content_matching:
            msg += " and"
        msg += f"{lpad}< {docs_count} >{rpad} document"
        if docs_count != 1:
            msg += "s"
        else:
            msg += "s"
    msg += " [Yes/skip]? "

    if msg != last_msg:
        if last_msg:
            msg_full = "\r" + " " * len(last_msg) + "\r" + msg
        else:
            msg_full = msg
    else:
        msg_full = None

    rlist: list[TextIO] = []
    if try_number > 1:
        rlist, _, _ = select.select(
            [sys.stdin], [], [], ctx.selenium_poll_frequency_secs)

    if not rlist and msg_full:
        sys.stdout.write(msg_full)
        sys.stdout.flush()

    if not rlist:
        rlist, _, _ = select.select(
            [sys.stdin], [], [], ctx.selenium_poll_frequency_secs)
    result = None
    if rlist:
        result = parse_prompt_option(
            sys.stdin.readline(),
            [(InteractiveResult.ACCEPT, YES_INDICATING_STRINGS),
             (InteractiveResult.SKIP_DOC, set_join(SKIP_INDICATING_STRINGS, NO_INDICATING_STRINGS))],
            InteractiveResult.ACCEPT
        )
        if result is None:
            print('please answer with "yes" or "skip"')
            sys.stdout.write(msg)
            sys.stdout.flush()
    return result, msg


def handle_match_chain(mc: MatchChain, doc: Document, last_doc_path) -> tuple[bool, bool]:
    if mc.need_content_matches():
        content_matches, mc.labels_none_for_n = gen_content_matches(
            mc, doc, last_doc_path)
    else:
        content_matches = []

    if mc.need_document_matches(True):
        document_matches = gen_document_matches(mc, doc, last_doc_path)
    else:
        document_matches = []

    if mc.selenium_strategy != SeleniumStrategy.DEDUP:
        mc.content_matches = content_matches
        mc.document_matches = document_matches
    else:
        for cm in content_matches:
            if cm in mc.handled_content_matches:
                continue
            mc.handled_content_matches.add(cm)
            mc.content_matches.append(cm)

        for dm in document_matches:
            if dm in mc.handled_document_matches:
                continue
            cm.mc.handled_document_matches.add(dm)
            mc.document_matches.append(dm)

    waiting = True
    interactive = False
    if mc.selenium_strategy == SeleniumStrategy.DISABLED:
        waiting = False
    elif mc.selenium_strategy == SeleniumStrategy.FIRST:
        contents_missing = not content_matches and mc.need_content_matches()
        documents_missing = (
            not mc.document_matches
            and mc.need_document_matches(True)
        )
        if not contents_missing or not documents_missing:
            waiting = False
    else:
        assert mc.selenium_strategy in [
            SeleniumStrategy.INTERACTIVE, SeleniumStrategy.DEDUP
        ]
        interactive = True

    return waiting, interactive


def accept_for_match_chain(
    mc: MatchChain, doc: Document,
    content_skip_doc: bool, documents_skip_doc: bool,
    new_docs: list[Document]
) -> tuple[bool, bool]:
    if not mc.ci_continuous:
        mc.ci = mc.cimin
    if not content_skip_doc:
        for i, cm in enumerate(mc.content_matches):
            if not mc.has_label_matching or cm.label_regex_match is not None:
                if mc.ci > mc.cimax:
                    break
                res = handle_content_match(cm)
                if res == InteractiveResult.SKIP_CHAIN:
                    break
                if res == InteractiveResult.SKIP_DOC:
                    content_skip_doc = True
                    break
            else:
                log(
                    mc.ctx,
                    Verbosity.WARN,
                    f"no labels: skipping remaining {len(mc.content_matches) - i}"
                    + " content element(s) in document:\n    {doc.path}"
                )
                break
    if not documents_skip_doc:
        for d in mc.document_matches:
            res = handle_document_match(mc, d)
            if res == InteractiveResult.SKIP_CHAIN:
                break
            if res == InteractiveResult.SKIP_DOC:
                documents_skip_doc = True
                break
            if res == InteractiveResult.ACCEPT:
                new_docs.append(d)
    mc.document_matches.clear()
    mc.content_matches.clear()
    mc.handled_document_matches.clear()
    mc.handled_content_matches.clear()
    mc.di += 1
    return content_skip_doc, documents_skip_doc


def decide_document_encoding(ctx: ScrepContext, doc: Document) -> str:
    forced = False
    mc = doc.src_mc
    if not mc:
        mc = ctx.match_chains[0]
    if mc.forced_document_encoding:
        enc = mc.forced_document_encoding
        forced = True
    elif doc.encoding:
        enc = doc.encoding
    else:
        enc = mc.default_document_encoding
    doc.encoding = enc
    doc.forced_encoding = forced
    return enc


def parse_xml(ctx: ScrepContext, doc: Document) -> None:
    try:
        text = cast(str, doc.text)
        src_bytes = text.encode(cast(str, doc.encoding),
                                errors="surrogateescape")
        if text.strip() == "":
            src_xml = lxml.etree.Element("html")
        elif doc.forced_encoding:
            src_xml = lxml.html.fromstring(
                src_bytes,
                parser=lxml.html.HTMLParser(encoding=doc.encoding)
            )
        else:
            src_xml = lxml.html.fromstring(src_bytes)
        doc.xml = src_xml
    except (lxml.etree.LxmlError, UnicodeEncodeError, UnicodeDecodeError) as ex:
        log(ctx, Verbosity.ERROR,
            f"{doc.path}: failed to parse as xml: {str(ex)}")


def dl(ctx: ScrepContext) -> Optional[Document]:
    doc = None
    while ctx.docs:
        doc = ctx.docs.popleft()
        last_doc_path = doc.path
        unsatisfied_chains = 0
        have_xpath_matching = 0
        for mc in doc.match_chains:
            if mc.need_document_matches(False) or mc.need_content_matches():
                unsatisfied_chains += 1
                mc.satisfied = False
                if mc.has_xpath_matching:
                    have_xpath_matching += 1

        if unsatisfied_chains == 0:
            if ctx.selenium_variant == SeleniumVariant.DISABLED or (doc is ctx.reused_doc and not ctx.changed_selenium):
                continue

        log(ctx, Verbosity.INFO,
            f"handling {document_type_display_dict[doc.document_type]} '{doc.path}'")

        try_number = 0
        try:
            fetch_doc(ctx, doc)
        except SeleniumWebDriverException as ex:
            if selenium_has_died(ctx):
                report_selenium_died(ctx)
            else:
                log(ctx, Verbosity.ERROR,
                    f"Failed to fetch {doc.path}: {str(ex)}")
            break
        except ScrepFetchError as ex:
            log(ctx, Verbosity.ERROR, f"Failed to fetch {doc.path}: {str(ex)}")
            continue
        static_content = (
            doc.document_type != DocumentType.URL or ctx.selenium_variant == SeleniumVariant.DISABLED)
        last_msg = ""
        while unsatisfied_chains > 0:
            try_number += 1
            same_content = static_content and try_number > 1
            if try_number > 1 and not static_content:
                assert(ctx.selenium_variant != SeleniumVariant.DISABLED)
                try:
                    drv = cast(SeleniumWebDriver, ctx.selenium_driver)
                    last_doc_path = drv.current_url
                    src_new, xml_new = selenium_get_full_page_source(ctx)
                    same_content = (src_new == doc.text)
                    doc.text = src_new
                    doc.xml = xml_new
                except SeleniumWebDriverException as ex:
                    if selenium_has_died(ctx):
                        report_selenium_died(ctx)
                    else:
                        log(ctx, Verbosity.ERROR,
                            f"selenium failed to fetch page source: {str(ex)}")
                    break

            if not same_content:
                interactive_chains = []
                if have_xpath_matching and doc.xml is None:
                    parse_xml(ctx, doc)
                    if doc.xml is None:
                        break

                for mc in doc.match_chains:
                    if mc.satisfied:
                        continue
                    waiting, interactive = handle_match_chain(
                        mc, doc, last_doc_path)
                    if not waiting:
                        mc.satisfied = True
                        unsatisfied_chains -= 1
                        if mc.has_xpath_matching:
                            have_xpath_matching -= 1
                    elif interactive:
                        interactive_chains.append(mc)

            if interactive_chains:
                accept, last_msg = handle_interactive_chains(
                    ctx, interactive_chains, doc,
                    last_doc_path, try_number, last_msg
                )
                sat = (accept == InteractiveResult.ACCEPT)
                if accept:
                    for mc in interactive_chains:
                        mc.satisfied = sat
                        unsatisfied_chains -= 1
                        if mc.has_xpath_matching:
                            have_xpath_matching -= 1

            if unsatisfied_chains and not interactive_chains:
                if static_content:
                    break
                time.sleep(ctx.selenium_poll_frequency_secs)
        new_docs: list[Document] = []
        content_skip_doc, doc_skip_doc = False, False
        for mc in doc.match_chains:
            if not mc.satisfied:
                # ignore skipped chains
                continue
            content_skip_doc, doc_skip_doc = accept_for_match_chain(
                mc, doc, content_skip_doc, doc_skip_doc, new_docs
            )
        if mc.ctx.documents_bfs:
            mc.ctx.docs.extend(new_docs)
        else:
            mc.ctx.docs.extendleft(reversed(new_docs))
    return doc


def finalize(ctx: ScrepContext) -> None:
    if ctx.dl_manager:
        try:
            ctx.dl_manager.pom.main_thread_done()
            ctx.dl_manager.terminate()
        finally:
            ctx.dl_manager = None
    if ctx.selenium_driver and not ctx.selenium_keep_alive and not selenium_has_died(ctx):
        try:
            ctx.selenium_driver.close()
        except SeleniumWebDriverException:
            pass
        finally:
            ctx.selenium_driver = None
    if ctx.downloads_temp_dir:
        try:
            shutil.rmtree(ctx.downloads_temp_dir)
        finally:
            ctx.downloads_temp_dir = None


def begins(string, begin) -> bool:
    return len(string) >= len(begin) and string[0:len(begin)] == begin


def parse_mc_range_int(ctx: ScrepContext, v, arg) -> int:
    try:
        return int(v)
    except ValueError as ex:
        raise ScrepSetupError(
            f"failed to parse '{v}' as an integer for match chain specification of '{arg}'"
        )


def extend_match_chain_list(ctx: ScrepContext, needed_id: int) -> None:
    if len(ctx.match_chains) > needed_id:
        return
    for i in range(len(ctx.match_chains), needed_id+1):
        mc = copy.deepcopy(ctx.origin_mc)
        mc.chain_id = i
        ctx.match_chains.append(mc)


def parse_simple_mc_range(ctx: ScrepContext, mc_spec: str, arg: str) -> Iterable[MatchChain]:
    sections = mc_spec.split(",")
    ranges = []
    for s in sections:
        s = s.strip()
        if s == "":
            raise ScrepSetupError(
                "invalid empty range in match chain specification of '{arg}'")
        dash_split = [r.strip() for r in s.split("-")]
        if len(dash_split) > 2 or s == "-":
            raise ScrepSetupError(
                "invalid range '{s}' in match chain specification of '{arg}'")
        if len(dash_split) == 1:
            id = parse_mc_range_int(ctx, dash_split[0], arg)
            extend_match_chain_list(ctx, id)
            ranges.append([ctx.match_chains[id]])
        else:
            lhs, rhs = dash_split
            if lhs == "":
                fst = 0
            else:
                fst = parse_mc_range_int(ctx, lhs, arg)
            if rhs == "":
                extend_match_chain_list(ctx, fst)
                snd = len(ctx.match_chains) - 1
                ranges.append([ctx.origin_mc])
            else:
                snd = parse_mc_range_int(ctx, dash_split[1], arg)
                if fst > snd:
                    raise ScrepSetupError(
                        f"second value must be larger than first for range {s} "
                        + f"in match chain specification of '{arg}'"
                    )
                extend_match_chain_list(ctx, snd)
            ranges.append(ctx.match_chains[fst: snd + 1])
    return itertools.chain(*ranges)


def parse_mc_range(ctx: ScrepContext, mc_spec: str, arg: str) -> Iterable[MatchChain]:
    if mc_spec == "":
        return [ctx.defaults_mc]

    esc_split = [x.strip() for x in mc_spec.split("^")]
    if len(esc_split) > 2:
        raise ScrepSetupError(
            f"cannot have more than one '^' in match chain specification of '{arg}'"
        )
    if len(esc_split) == 1:
        return parse_simple_mc_range(ctx, mc_spec, arg)
    lhs, rhs = esc_split
    if lhs == "":
        exclude = parse_simple_mc_range(ctx, rhs, arg)
        include: Iterable[MatchChain] = itertools.chain(
            ctx.match_chains, [ctx.origin_mc])
    else:
        exclude = parse_simple_mc_range(ctx, rhs, arg)
        chain_count = len(ctx.match_chains)
        include = parse_simple_mc_range(ctx, lhs, arg)
        # hack: parse exclude again so the newly generated chains form include are respected
        if chain_count != len(ctx.match_chains):
            exclude = parse_simple_mc_range(ctx, rhs, arg)
    return ({*include} - {*exclude})


def parse_mc_arg(
    ctx: ScrepContext, argname: str, arg: str,
    support_blank: bool = False, blank_value: str = ""
) -> Optional[tuple[Iterable[MatchChain], str]]:
    if not begins(arg, argname):
        return None
    argname_len = len(argname)
    eq_pos = arg.find("=")
    if eq_pos == -1:
        if arg != argname:
            return None
        if not support_blank:
            raise ScrepSetupError("missing equals sign in argument '{arg}'")
        pre_eq_arg = arg
        value = blank_value
        mc_spec = arg[argname_len:]
    else:
        mc_spec = arg[argname_len: eq_pos]
        if not CHAIN_REGEX.match(mc_spec):
            return None
        pre_eq_arg = arg[:eq_pos]
        value = arg[eq_pos+1:]
    return parse_mc_range(ctx, mc_spec, pre_eq_arg), value


def parse_mc_arg_as_range(ctx: ScrepContext, argname: str, argval: str) -> list[MatchChain]:
    return list(parse_mc_range(ctx, argval, argname))


def apply_mc_arg(
    ctx: ScrepContext, argname: str, config_opt_names: list[str], arg: str,
    value_parse: Callable[[str, str], Any] = lambda x, _arg: x,
    support_blank=False, blank_value: str = ""
) -> bool:
    parse_result = parse_mc_arg(
        ctx, argname, arg, support_blank, blank_value)
    if parse_result is None:
        return False
    mcs, value = parse_result
    value = value_parse(value, arg)
    mcs = list(mcs)
    # so the lowest possible chain generates potential errors
    mcs.sort(key=lambda mc: mc.chain_id if mc.chain_id else float("inf"))
    for mc in mcs:
        prev = mc.try_set_config_option(config_opt_names, value, arg)
        if prev is not None:
            if mc is ctx.origin_mc:
                chainid = str(max(len(ctx.match_chains), 1))
            elif mc is ctx.defaults_mc:
                chainid = ""
            else:
                chainid = str(mc.chain_id)
            raise ScrepSetupError(
                f"{argname}{chainid} specified twice in: "
                + f"'{prev}' and '{arg}'"
            )

    return True


def get_arg_val(arg: str) -> str:
    return arg[arg.find("=") + 1:]


def parse_bool_arg(v: str, arg: str, blank_val: bool = True) -> bool:
    v = v.strip().lower()
    if v == "" and blank_val is not None:
        return blank_val

    if v in YES_INDICATING_STRINGS:
        return True
    if v in NO_INDICATING_STRINGS:
        return False
    raise ScrepSetupError(f"cannot parse '{v}' as a boolean in '{arg}'")


def parse_int_arg(v: str, arg: str) -> int:
    try:
        return int(v)
    except ValueError:
        raise ScrepSetupError(f"cannot parse '{v}' as an integer in '{arg}'")


def parse_non_negative_float_arg(v: str, arg: str) -> float:
    try:
        f = float(v)
    except ValueError:
        raise ScrepSetupError(f"cannot parse '{v}' as an number in '{arg}'")
    if f < 0:
        raise ScrepSetupError(f"negative number '{v}' not allowed for '{arg}'")
    return f


def parse_encoding_arg(v: str, arg: str) -> str:
    if not verify_encoding(v):
        raise ScrepSetupError(f"unknown encoding in '{arg}'")
    return v


def select_variant(val: str, variants_dict: dict[str, T]) -> Optional[T]:
    val = val.strip().lower()
    if val == "":
        return None
    if val in variants_dict:
        return variants_dict[val]
    match = None
    for k, v in variants_dict.items():
        if begins(k, val):
            if match is not None:
                return None
            match = v
    return match


def parse_variant_arg(val: str, variants_dict: dict[str, T], arg: str) -> T:
    res = select_variant(val, variants_dict)
    if res is None:
        raise ScrepSetupError(
            f"illegal argument '{arg}', valid options for "
            + f"{arg[:len(arg)-len(val)-1]} are: "
            + f"{', '.join(sorted(variants_dict.keys()))}"
        )
    return res


def verify_encoding(encoding: str) -> bool:
    try:
        "!".encode(encoding=encoding)
        return True
    except UnicodeEncodeError:
        return False


def apply_doc_arg(
    ctx: ScrepContext, argname: str, doctype: DocumentType, arg: str
) -> bool:
    parse_result = parse_mc_arg(ctx, argname, arg)
    if parse_result is None:
        return False
    mcs, path = parse_result
    mcs = list(mcs)
    if mcs == [ctx.defaults_mc]:
        extend_chains_above = len(ctx.match_chains)
        mcs = list(ctx.match_chains)
    elif ctx.origin_mc in mcs:
        mcs.remove(ctx.origin_mc)
        extend_chains_above = len(ctx.match_chains)
    else:
        extend_chains_above = None
    path, path_parsed = normalize_link(
        ctx,
        None,
        Document(doctype.url_handling_type(), "", None),
        None,
        path,
        urllib.parse.urlparse(path)
    )
    doc = Document(
        doctype,
        path,
        None,
        mcs,
        extend_chains_above,
        path_parsed=path_parsed
    )
    ctx.docs.append(doc)
    return True


def apply_ctx_arg(
    ctx: ScrepContext, optname: str, argname: str, arg: str,
    value_parse: Callable[[str, str], Any] = lambda x, _arg: x,
    support_blank: bool = False,
    blank_val: str = ""
) -> bool:
    if not begins(arg, optname):
        return False
    if len(optname) == len(arg):
        if support_blank:
            val = blank_val
        else:
            raise ScrepSetupError(
                f"missing '=' and value for option '{optname}'"
            )
    else:
        nc = arg[len(optname):]
        if CHAIN_REGEX.match(nc):
            raise ScrepSetupError(
                "option '{optname}' does not support match chain specification"
            )
        if nc[0] != "=":
            return False
        val = get_arg_val(arg)
    if ctx.__dict__[argname] is not None:
        raise ScrepSetupError(f"error: {argname} specified twice")
    ctx.__dict__[argname] = value_parse(val, arg)
    return True


def resolve_repl_defaults(
    ctx_new: ScrepContext, ctx: ScrepContext, last_doc: Optional[Document]
) -> None:
    if ctx_new.user_agent_random and not ctx_new.user_agent:
        ctx.user_agent = None

    if ctx_new.user_agent and not ctx_new.user_agent_random:
        ctx.user_agent_random = None

    ctx_new.apply_defaults(ctx)

    if ctx_new.max_download_threads != ctx.max_download_threads:
        if ctx.dl_manager is not None:
            try:
                ctx.dl_manager.terminate()
            finally:
                ctx.dl_manager = None
    changed_selenium = False
    if ctx_new.selenium_variant != ctx.selenium_variant:
        changed_selenium = True
        try:
            if ctx.selenium_driver:
                ctx.selenium_driver.close()
        except SeleniumWebDriverException:
            pass
        finally:
            ctx_new.selenium_driver = None
            ctx.selenium_driver = None

    if ctx_new.selenium_driver:
        doc_url = None
        try:
            doc_url = ctx_new.selenium_driver.current_url
        except SeleniumWebDriverException as ex:
            # selenium died, abort
            if selenium_has_died(ctx_new):
                report_selenium_died(ctx_new)
                last_doc = None
        if doc_url:
            if begins(doc_url, "file:"):
                path = doc_url[len("file:"):]
                if not last_doc or os.path.realpath(last_doc.path) != os.path.realpath(path):
                    doctype = DocumentType.FILE
                    if last_doc and last_doc.document_type == DocumentType.RFILE:
                        doctype = DocumentType.RFILE
                    last_doc = Document(
                        doctype, path, None, None, None
                    )
            else:
                if not last_doc or doc_url != last_doc.path:
                    last_doc = Document(
                        DocumentType.URL, doc_url, None, None, None
                    )

    if not ctx_new.docs and last_doc:
        last_doc.expand_match_chains_above = len(ctx_new.match_chains)
        last_doc.match_chains = list(ctx_new.match_chains)
        ctx_new.reused_doc = last_doc
        ctx_new.docs.append(last_doc)
    ctx_new.changed_selenium = changed_selenium
    if changed_selenium and last_doc:
        last_doc.text = None
        last_doc.xml = None


def run_repl(ctx: ScrepContext) -> int:
    try:
        # run with initial args
        readline.add_history(shlex.join(sys.argv[1:]))
        tty = sys.stdin.isatty()
        while True:
            try:
                try:
                    last_doc = dl(ctx)
                except ScrepMatchError as ex:
                    log(ctx, Verbosity.ERROR, str(ex))
                if ctx.dl_manager:
                    ctx.dl_manager.pom.main_thread_done()
                    ctx.dl_manager.wait_until_jobs_done()
                sys.stdout.flush()
                if ctx.exit:
                    return ctx.error_code
                try:
                    line = input("screp> " if tty else "")
                except EOFError:
                    if tty:
                        print("")
                    return 0
                args = shlex.split(line)
                if not len(args):
                    continue

                ctx_new = ScrepContext(blank=True)
                try:
                    parse_args(ctx_new, args)
                except ScrepSetupError as ex:
                    log(ctx, Verbosity.ERROR, str(ex))
                    continue

                resolve_repl_defaults(ctx_new, ctx, last_doc)
                ctx_old = ctx
                ctx = ctx_new

                try:
                    setup(ctx, True)
                except ScrepSetupError as ex:
                    if ctx.exit:
                        ctx_old.exit = True
                        ctx_old.error_code = ctx.error_code
                    ctx = ctx_old
                    log(ctx, Verbosity.ERROR, str(ex))
                    continue
            except KeyboardInterrupt:
                print("")
                continue
    finally:
        finalize(ctx)


def parse_args(ctx: ScrepContext, args: Iterable[str]) -> None:
    for arg in args:
        if (
            arg in ["-h", "--help", "help"]
            or (begins(arg, "help=") and parse_bool_arg(arg[len("help="):], arg))
        ):
            help()
            sys.exit(0)
         # content args
        if apply_mc_arg(ctx, "cx", ["content", "xpath"], arg):
            continue
        if apply_mc_arg(ctx, "cr", ["content", "regex"], arg):
            continue
        if apply_mc_arg(ctx, "cf", ["content", "format"], arg):
            continue
        if apply_mc_arg(ctx, "cmm", ["content", "multimatch"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "cin", ["content", "interactive"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "cfc", ["content_forward_chains"], arg, lambda v, arg: parse_mc_arg_as_range(ctx, arg, v)):
            continue

        if apply_mc_arg(ctx, "cimin", ["cimin"], arg, parse_int_arg):
            continue
        if apply_mc_arg(ctx, "cimax", ["cimax"], arg, parse_int_arg):
            continue
        if apply_mc_arg(ctx, "cicont", ["ci_continuous"], arg, parse_bool_arg, True):
            continue

        if apply_mc_arg(ctx, "cff", ["content_forward_format"], arg):
            continue
        if apply_mc_arg(ctx, "cpf", ["content_print_format"], arg):
            continue
        if apply_mc_arg(ctx, "cwf", ["content_write_format"], arg):
            continue
        if apply_mc_arg(ctx, "csf", ["content_save_format"], arg):
            continue
        if apply_mc_arg(ctx, "csin", ["save_path_interactive"], arg, parse_bool_arg, True):
            continue

        if apply_mc_arg(ctx, "cienc", ["content_input_encoding"], arg, parse_encoding_arg):
            continue
        if apply_mc_arg(ctx, "cfienc", ["content_forced_input_encoding"], arg, parse_encoding_arg):
            continue

        if apply_mc_arg(ctx, "cl", ["content_raw"], arg, lambda v, arg: not parse_bool_arg(v, arg), True): continue
        if apply_mc_arg(ctx, "cesc", ["content_escape_sequence"], arg):
            continue

        # label args
        if apply_mc_arg(ctx, "lx", ["label", "xpath"], arg):
            continue
        if apply_mc_arg(ctx, "lr", ["label", "regex"], arg):
            continue
        if apply_mc_arg(ctx, "lf", ["label", "format"], arg):
            continue
        if apply_mc_arg(ctx, "lmm", ["label", "multimatch"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "lin", ["label", "interactive"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "las", ["allow_slashes_in_labels"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "lic", ["labels_inside_content"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "lam", ["label_allow_missing"], arg, parse_bool_arg, True):
            continue

        # document args
        if apply_mc_arg(ctx, "dx", ["document", "xpath"], arg):
            continue
        if apply_mc_arg(ctx, "dr", ["document", "regex"], arg):
            continue
        if apply_mc_arg(ctx, "df", ["document", "format"], arg):
            continue
        if apply_mc_arg(ctx, "doc", ["document_output_chains"], arg, lambda v, arg: parse_mc_arg_as_range(ctx, arg, v)):
            continue
        if apply_mc_arg(ctx, "dmm", ["document", "multimatch"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "din", ["document", "interactive"], arg, parse_bool_arg, True):
            continue

        if apply_mc_arg(ctx, "dimin", ["dimin"], arg, parse_int_arg):
            continue
        if apply_mc_arg(ctx, "dimax", ["dimax"], arg, parse_int_arg):
            continue

        if apply_mc_arg(ctx, "owf", ["overwrite_files"], arg, parse_bool_arg, True):
            continue

        if apply_mc_arg(ctx, "denc", ["default_document_encoding"], arg, parse_encoding_arg):
            continue
        if apply_mc_arg(ctx, "dfenc", ["forced_document_encoding"], arg, parse_encoding_arg):
            continue

        if apply_mc_arg(ctx, "dsch", ["default_document_scheme"], arg):
            continue
        if apply_mc_arg(ctx, "dpsch", ["prefer_parent_document_scheme"], arg):
            continue
        if apply_mc_arg(ctx, "dfsch", ["forced_document_scheme"], arg):
            continue

        if apply_mc_arg(ctx, "selstrat", ["selenium_strategy"], arg, lambda v, arg: parse_variant_arg(v, selenium_strats_dict, arg)): continue
        if apply_mc_arg(ctx, "seldl", ["selenium_download_strategy"], arg, lambda v, arg: parse_variant_arg(v, selenium_download_strategies_dict, arg)): continue
        # misc args
        if apply_doc_arg(ctx, "url", DocumentType.URL, arg):
            continue
        if apply_doc_arg(ctx, "rfile", DocumentType.RFILE, arg):
            continue
        if apply_doc_arg(ctx, "file", DocumentType.FILE, arg):
            continue

        if apply_ctx_arg(ctx, "cookiefile", "cookie_file", arg):
            continue

        if apply_ctx_arg(ctx, "sel", "selenium_variant", arg, lambda v, arg: parse_variant_arg(v, selenium_variants_dict, arg)):
            continue
        if apply_ctx_arg(ctx, "selkeep", "selenium_keep_alive", arg, parse_bool_arg, True):
            continue
        if apply_ctx_arg(ctx, "tbdir", "tor_browser_dir", arg):
            continue
        if apply_ctx_arg(ctx, "bfs", "documents_bfs", arg, parse_bool_arg, True):
            continue
        if apply_ctx_arg(ctx, "ua", "user_agent", arg):
            continue
        if apply_ctx_arg(ctx, "uar", "user_agent_random", arg, parse_bool_arg, True):
            continue
        if apply_ctx_arg(ctx, "v", "verbosity", arg, lambda v, arg: parse_variant_arg(v, verbosities_dict, arg)):
            continue

        if apply_ctx_arg(ctx, "repl", "repl", arg,  parse_bool_arg, True):
            continue

        if apply_ctx_arg(ctx, "mt", "max_download_threads", arg,  parse_int_arg):
            continue

        if apply_ctx_arg(ctx, "--repl", "repl", arg,  parse_bool_arg, True):
            continue

        if apply_ctx_arg(ctx, "exit", "exit", arg,  parse_bool_arg, True):
            continue

        if apply_ctx_arg(ctx, "timeout", "request_timeout_seconds", arg,  parse_non_negative_float_arg):
            continue

        raise ScrepSetupError(f"unrecognized option: '{arg}'")


def main() -> int:
    ctx = ScrepContext(blank=True)
    if len(sys.argv) < 2:
        log_raw(
            Verbosity.ERROR,
            f"missing command line options. Consider {sys.argv[0]} --help"
        )
        return 1

    try:
        parse_args(ctx, sys.argv[1:])
        setup(ctx)
    except ScrepSetupError as ex:
        log_raw(Verbosity.ERROR, str(ex))
        return 1

    if ctx.repl:
        ec = run_repl(ctx)
    else:
        try:
            dl(ctx)
        except ScrepMatchError as ex:
            log(ctx, Verbosity.ERROR, str(ex))
        finally:
            finalize(ctx)
        ec = ctx.error_code
    return ec


if __name__ == "__main__":
    try:
        # to silence: "Setting a profile has been deprecated" on launching tor
        warnings.filterwarnings(
            "ignore", module=".*selenium.*", category=DeprecationWarning
        )
        exit(main())
    except BrokenPipeError:
        abort_on_broken_pipe()
    except KeyboardInterrupt:
        sys.exit(1)
