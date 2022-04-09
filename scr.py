#!/usr/bin/env python3

from codecs import strict_errors
import functools
import subprocess
from unittest import expectedFailure
import selenium.webdriver
from abc import ABC, abstractmethod
import multiprocessing
from typing import Any, Callable, Iterable, Iterator, Optional, TypeVar, BinaryIO, TextIO, Union, cast
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
import pyrfc6266
import requests
import sys
import xml.sax.saxutils
import select
import textwrap
import re
import math
import concurrent.futures
import os
from string import Formatter
import readline
import urllib.parse
from http.cookiejar import MozillaCookieJar
from random_user_agent.user_agent import UserAgent
import pyparsing.exceptions
from tbselenium.tbdriver import TorBrowserDriver
import selenium
import selenium.webdriver.common.by
from selenium.webdriver.remote.webelement import WebElement as SeleniumWebElement
from selenium.webdriver.firefox.service import Service as SeleniumFirefoxService
from selenium.webdriver.chrome.service import Service as SeleniumChromeService
from selenium.webdriver.remote.webdriver import WebDriver as SeleniumWebDriver
import selenium.common.exceptions
from selenium.common.exceptions import WebDriverException as SeleniumWebDriverException
from selenium.common.exceptions import TimeoutException as SeleniumTimeoutException
import geckodriver_autoinstaller
# this is of course not really a selenium exception,
# but selenium throws it arbitrarily, just like SeleniumWebDriverException,
# and that is the only way in which we use it
from urllib3.exceptions import MaxRetryError as SeleniumMaxRetryError
import selenium.webdriver.firefox.webdriver
from collections import deque, OrderedDict
from enum import Enum, IntEnum
import time
import datetime
import tempfile
import itertools
import warnings
import urllib.request

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")

# because for python, sys.argv[0] does not reflect what the user typed anyways,
# we just use this fixed value for --help etc.
SCRIPT_NAME = "scr"
VERSION = "0.5.1"

SCR_USER_AGENT = f"{SCRIPT_NAME}/{VERSION}"

FALLBACK_DOCUMENT_SCHEME = "https"

DEFAULT_TIMEOUT_SECONDS = 30

DOWNLOAD_STATUS_LOG_ELEMENTS = 20
DOWNLOAD_STATUS_LOG_TIME = 10
DOWNLOAD_STATUS_NAME_LENGTH = 60
DOWNLOAD_STATUS_BAR_LENGTH = 30
DOWNLOAD_STATUS_REFRESH_INTERVAL = 0.1
DEFAULT_TRUNCATION_LENGTH = 200
DEFAULT_RESPONSE_BUFFER_SIZE = 32768
DEFAULT_MAX_PRINT_BUFFER_CAPACITY = 2**20 * 100  # 100 MiB

# mimetype to use for selenium downloading to avoid triggering pdf viewers etc.
DUMMY_MIMETYPE = "application/zip"

DEFAULT_CPF = "{c}\\n"
DEFAULT_CWF = "{c}"
DEFAULT_CSF = "{fn}"
DEFAULT_ESCAPE_SEQUENCE = "<END>"


def prefixes(str: str) -> set[str]:
    return set(str[:i] for i in range(len(str), 0, -1))


def set_join(*args: Iterable[T]) -> set[T]:
    res: set[T] = set()
    for s in args:
        res.update(s)
    return res


class OptionIndicatingStrings:
    representative: str
    matching: set[str]

    def __init__(self, representative: str, *args: set[str]) -> None:
        self.representative = representative
        if args:
            self.matching = set_join(*args)
        else:
            self.matching = prefixes(representative)


YES_INDICATING_STRINGS = OptionIndicatingStrings(
    "yes",
    prefixes("yes"), prefixes("true"), {"1", "+"}
)
NO_INDICATING_STRINGS = OptionIndicatingStrings(
    "no", prefixes("no"), prefixes("false"), {"0", "-"}
)
SKIP_INDICATING_STRINGS = OptionIndicatingStrings("skip")
CHAIN_SKIP_INDICATING_STRINGS = OptionIndicatingStrings("chainskip")
EDIT_INDICATING_STRINGS = OptionIndicatingStrings("edit")
DOC_SKIP_INDICATING_STRINGS = OptionIndicatingStrings("docskip")
INSPECT_INDICATING_STRINGS = OptionIndicatingStrings("inspect")
ACCEPT_CHAIN_INDICATING_STRINGS = OptionIndicatingStrings("acceptchain")

MATCH_CHAIN_ARGUMENT_REGEX = re.compile("^[0-9\\-\\*\\^]*$")


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

    def derived_type(self) -> 'DocumentType':
        if self == DocumentType.RFILE:
            return DocumentType.URL
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

    def read(self, size: Optional[int] = None) -> bytes:
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


class LocatorMatch:
    xmatch: Optional[str] = None
    xmatch_xml: Optional[lxml.html.HtmlElement] = None
    rmatch: Optional[str] = None
    fres: Optional[str] = None
    jsres: Optional[str] = None
    result: str = ""
    named_cgroups: Optional[dict[str, str]] = None
    unnamed_cgroups: Optional[list[str]] = None

    def set_regex_match(self, match: re.Match[str]) -> None:
        self.result = match.group(0)
        self.rmatch = self.result
        self.named_cgroups = {
            k: (v if v is not None else "")
            for (k, v) in match.groupdict().items()
        }
        self.unnamed_cgroups = [
            x if x is not None else "" for x in match.groups()
        ]

    def __key__(self) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        # we only ever compare locator matches from the same match chain
        # therefore it is enough that the complete match is equivalent
        return (self.xmatch, self.rmatch, self.fres, self.jsres)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, self.__class__) and self.__key__() == other.__key__()

    def __hash__(self) -> int:
        return hash(self.__key__())

    def unnamed_group_list_to_dict(self, name_prefix: str) -> dict[str, str]:
        if self.rmatch is None:
            return {}
        group_dict = {f"{name_prefix}0": self.rmatch}
        for i, g in enumerate(cast(list[str], self.unnamed_cgroups)):
            group_dict[f"{name_prefix}{i+1}"] = g
        return group_dict

    def clone(self) -> 'LocatorMatch':
        c = LocatorMatch()
        if self.xmatch is not None:
            c.xmatch = self.xmatch
        if self.xmatch_xml is not None:
            c.xmatch_xml = self.xmatch_xml
        if self.rmatch is not None:
            c.rmatch = self.rmatch
        if self.fres is not None:
            c.fres = self.fres
        if self.jsres is not None:
            c.jsres = self.jsres
        if self.result is not None:
            c.result = self.result
        if self.named_cgroups is not None:
            c.named_cgroups = self.named_cgroups
        if self.unnamed_cgroups is not None:
            c.unnamed_cgroups = self.unnamed_cgroups
        return c


class Document:
    document_type: DocumentType
    path: str
    path_parsed: urllib.parse.ParseResult
    encoding: Optional[str]
    forced_encoding: bool
    text: Optional[str]
    xml: Optional[lxml.html.HtmlElement]
    src_mc: Optional['MatchChain']
    locator_match: Optional[LocatorMatch]
    dfmatch: Optional[str]

    def __init__(
        self, document_type: DocumentType, path: str,
        src_mc: Optional['MatchChain'],
        match_chains: Optional[list['MatchChain']] = None,
        expand_match_chains_above: Optional[int] = None,
        locator_match: Optional[LocatorMatch] = None,
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
        self.locator_match = locator_match
        self.dfmatch = None
        if not match_chains:
            self.match_chains = []
        else:
            self.match_chains = sorted(
                match_chains, key=lambda mc: mc.chain_id)
        self.expand_match_chains_above = expand_match_chains_above

    def __key__(self) -> tuple[DocumentType, str]:
        return (self.document_type, self.path)

    def __eq__(self, other: Any) -> bool:
        return isinstance(self, other.__class__) and self.__key__() == other.__key__()

    def __hash__(self) -> int:
        return hash(self.__key__())


class ConfigDataClass:
    _config_slots_: list[str] = []
    _subconfig_slots_: list[str] = []
    _final_values_: set[str]
    _value_sources_: dict[str, str]

    def __init__(self, blank: bool = False) -> None:
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

    def apply_defaults(self, defaults: 'ConfigDataClass') -> None:
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

    def resolve_attrib_path(
        self, attrib_path: list[str],
        transform: Optional[Callable[[Any], Any]] = None
    ) -> Any:
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
    regex: Optional[Union[str, re.Pattern[str]]] = None
    js_script: Optional[str] = None
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

    def is_active(self) -> bool:
        return any(x is not None for x in [self.xpath, self.regex, self.format, self.js_script])

    def setup_xpath(self, mc: 'MatchChain') -> None:
        if self.xpath is None:
            return
        try:
            xp = lxml.etree.XPath(self.xpath)
            xp.evaluate(lxml.html.HtmlElement("<div>test</div>"))
        except (lxml.etree.XPathSyntaxError, lxml.etree.XPathEvalError):
            # don't use the XPathSyntaxError message because they are spectacularily bad
            # e.g. XPath("/div/text(") -> XPathSyntaxError("Missing closing CURLY BRACE")
            raise ScrSetupError(
                f"invalid xpath in {self.get_configuring_argument(['xpath'])}"
            )
        self.xpath = xp

    def gen_dummy_locator_match(self) -> LocatorMatch:
        lm = LocatorMatch()
        if self.xpath:
            lm.xmatch = ""
        if self.regex and type(self.regex) is re.Pattern:
            lm.rmatch = ""
            capture_group_keys = list(self.regex.groupindex.keys())
            unnamed_regex_group_count = (
                self.regex.groups - len(capture_group_keys)
            )
            lm.named_cgroups = {k: "" for k in capture_group_keys}
            lm.unnamed_cgroups = [""] * unnamed_regex_group_count
        if self.format:
            lm.fres = ""
        if self.js_script:
            lm.jsres = ""
        return lm

    def setup_regex(self, mc: 'MatchChain') -> None:
        if self.regex is None:
            return
        try:
            self.regex = re.compile(self.regex, re.DOTALL | re.MULTILINE)
        except re.error as err:
            raise ScrSetupError(
                f"invalid regex ({err.msg}) in {self.get_configuring_argument(['regex'])}"
            )

    def setup_format(self, mc: 'MatchChain') -> None:
        if self.format is None:
            return
        validate_format(
            self, ["format"], mc.gen_dummy_content_match(), True, False
        )

    def setup_js(self, mc: 'MatchChain') -> None:
        if self.js_script is None:
            return
        args_dict: dict[str, Any] = {}
        dummy_doc = mc.gen_dummy_document()
        apply_general_format_args(dummy_doc, mc, args_dict, unstable_ci=True)
        apply_locator_match_format_args(
            self.name, self.gen_dummy_locator_match(), args_dict
        )
        js_prelude = ""
        for i, k in enumerate(args_dict.keys()):
            js_prelude += f"const {k} = arguments[{i}];\n"
        self.js_script = js_prelude + self.js_script

    def setup(self, mc: 'MatchChain') -> None:
        self.xpath = empty_string_to_none(self.xpath)
        assert self.regex is None or type(self.regex) is str
        self.regex = empty_string_to_none(self.regex)
        self.format = empty_string_to_none(self.format)
        self.setup_xpath(mc)
        self.setup_regex(mc)
        self.setup_js(mc)
        self.setup_format(mc)
        self.validated = True

    def match_xpath(
        self,
        src_text: str,
        src_xml: lxml.html.HtmlElement,
        doc_path: str,
        store_xml: bool = False
    ) -> list[LocatorMatch]:
        if self.xpath is None:
            lm = LocatorMatch()
            lm.result = src_text
            return [lm]
        try:
            xp = cast(lxml.etree.XPath, self.xpath)
            if type(src_xml) == lxml.etree._ElementUnicodeResult:
                # since lxml doesn't allow us to evaluate xpaths on these,
                # but we need it for lic, we hack in support for it by
                # generating a derived xpath that gets the expected results while
                # actually being evaluated on the parent
                fixed_xpath = f"./@{src_xml.attrname}"
                if xp.path[0:1] != "/":
                    fixed_xpath += "/"
                fixed_xpath += xp.path
                xpath_matches = src_xml.getparent().xpath(fixed_xpath)
            else:
                xpath_matches = (xp.evaluate(src_xml))
        except lxml.etree.XPathEvalError as ex:
            raise ScrMatchError(
                f"xpath matching failed for: '{self.xpath}' in {doc_path}"
            )
        except lxml.etree.LxmlError as ex:
            raise ScrMatchError(
                f"xpath '{self.xpath}' to {doc_path}: "
                + f"{ex.__class__.__name__}:  {str(ex)}"
            )

        if not isinstance(xpath_matches, list):
            raise ScrMatchError(
                f"xpath matching failed for: '{self.xpath}' in {doc_path}"
            )

        if len(xpath_matches) > 1 and not self.multimatch:
            xpath_matches = xpath_matches[:1]
        res = []
        for xm in xpath_matches:
            lm = LocatorMatch()
            if type(xm) == lxml.etree._ElementUnicodeResult:
                lm.xmatch = str(xm)
                if store_xml:
                    lm.xmatch_xml = xm
            else:
                try:
                    lm.result = lxml.html.tostring(xm, encoding="unicode")
                    lm.xmatch = lm.result
                    if store_xml:
                        lm.xmatch_xml = xm
                except (lxml.LxmlError, UnicodeEncodeError) as ex1:
                    raise ScrMatchError(
                        f"{doc_path}: xpath match encoding failed: {str(ex1)}"
                    )
            lm.result = lm.xmatch
            res.append(lm)
        return res

    def apply_regex_matches(
        self, lms: list[LocatorMatch],
        multimatch: Optional[bool] = None
    ) -> list[LocatorMatch]:
        if self.regex is None:
            return lms
        rgx = cast(re.Pattern[str], self.regex)
        if multimatch is None:
            multimatch = self.multimatch

        lms_new = []
        for lm in lms:
            if not multimatch:
                match = rgx.match(lm.result)
                if match:
                    lm.set_regex_match(match)
                    lms_new.append(lm)
                continue
            res: Optional[LocatorMatch] = lm
            for match in rgx.finditer(lm.result):
                if res is None:
                    res = lm.clone()
                res.set_regex_match(match)
                lms_new.append(res)
                if not multimatch:
                    break
                res = None
        return lms_new

    def apply_js_matches(
        self, doc: Document, mc: 'MatchChain', lms: list[LocatorMatch],
        multimatch: Optional[bool] = None
    ) -> list[LocatorMatch]:
        if self.js_script is None:
            return lms
        if multimatch is None:
            multimatch = self.multimatch
        lms_new: list[LocatorMatch] = []
        for lm in lms:
            args_dict: dict[str, Any] = {}
            apply_general_format_args(doc, mc, args_dict, unstable_ci=True)
            apply_locator_match_format_args(self.name, lm, args_dict)
            try:
                mc.js_executed = True
                drv = cast(SeleniumWebDriver, mc.ctx.selenium_driver)

                results = drv.execute_script(
                    self.js_script, *args_dict.values())  # type: ignore

            except selenium.common.exceptions.JavascriptException as ex:
                arg = cast(str, self.get_configuring_argument(['js_script']))
                name = arg[0: arg.find("=")]
                log(
                    mc.ctx, Verbosity.WARN,
                    f"{name}: js exception on {truncate(doc.path)}:\n{textwrap.indent(str(ex), '    ')}"
                )
                continue
            except (SeleniumWebDriverException, SeleniumMaxRetryError) as ex:
                if selenium_has_died(mc.ctx):
                    raise ScrMatchError(
                        "the selenium instance was closed unexpectedly")
                continue
            if results is None:
                continue
            if type(results) is not list:
                results = [str(results)]
            res: Optional[LocatorMatch] = lm
            for r in results:
                if res is None:
                    res = lm.clone()
                res.jsres = r
                res.result = r
                lms_new.append(res)
                if not multimatch:
                    break
                res = None
        return lms_new

    def apply_format_for_content_match(
        self, cm: 'ContentMatch', lm: LocatorMatch
    ) -> None:
        if not self.format:
            return
        lm.fres = self.format.format(**content_match_build_format_args(cm))
        lm.result = lm.fres

    def apply_format_for_document_match(
        self, doc: Document, mc: 'MatchChain', lm: LocatorMatch
    ) -> None:
        if not self.format:
            return
        args_dict: dict[str, Any] = {}
        apply_general_format_args(doc, mc, args_dict, unstable_ci=True)
        apply_locator_match_format_args(self.name, lm, args_dict)
        lm.fres = self.format.format(**args_dict)
        lm.result = lm.fres

    def is_unset(self) -> bool:
        return min([v is None for v in [self.xpath, self.regex, self.format]])


class MatchChain(ConfigDataClass):
    # config members
    ctx: 'ScrContext'  # this is a config member so it is copied on apply_defaults
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
    filename_default_format: Optional[str] = None
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

    selenium_strategy: SeleniumStrategy = SeleniumStrategy.PLAIN
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
    js_executed: bool = False
    has_xpath_matching: bool = False
    has_label_matching: bool = False
    has_content_xpaths: bool = False
    has_document_matching: bool = False
    has_content_matching: bool = False
    has_interactive_matching: bool = False
    need_content: bool = False
    need_label: bool = False
    need_filename: bool = False
    need_output_multipass: bool = False
    content_matches: list['ContentMatch']
    document_matches: list[Document]
    handled_content_matches: set['ContentMatch']
    handled_document_matches: set[Document]
    satisfied: bool = True
    labels_none_for_n: int = 0

    def __init__(self, ctx: 'ScrContext', chain_id: int, blank: bool = False) -> None:
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

    def gen_dummy_document(self) -> Document:
        d = Document(
            DocumentType.FILE, "", None,
            locator_match=self.document.gen_dummy_locator_match()
        )
        d.encoding = ""
        return d

    def gen_dummy_content_match(self) -> 'ContentMatch':
        clm = self.content.gen_dummy_locator_match()
        if self.has_label_matching:
            llm = self.label.gen_dummy_locator_match()
        elif self.label_default_format:
            llm = LocatorMatch()
            llm.fres = ""
        else:
            llm = None

        dcm = ContentMatch(clm, llm, self, self.gen_dummy_document())
        if self.content.multimatch:
            dcm.ci = 0
        if self.has_document_matching:
            dcm.di = 0
        return dcm

    def accepts_content_matches(self) -> bool:
        return self.di <= self.dimax

    def need_document_matches(self, current_di_used: int) -> bool:
        return (
            self.has_document_matching
            and self.di <= (self.dimax - (1 if current_di_used else 0))
        )

    def need_content_matches(self) -> bool:
        assert self.ci is not None and self.di is not None
        return self.has_content_matching and self.ci <= self.cimax and self.di <= self.dimax

    def is_valid_label(self, label: str) -> bool:
        if self.allow_slashes_in_labels:
            return True
        if "/" in label or "\\" in label:
            return False
        return True


class ContentMatch:
    clm: LocatorMatch
    llm: Optional[LocatorMatch] = None
    mc: MatchChain
    doc: Document

    # these are set once we accept the CM, not during it's creation
    ci: Optional[int] = None
    di: Optional[int] = None

    url_parsed: Optional[urllib.parse.ParseResult]

    def __init__(
        self,
        clm: LocatorMatch,
        llm: Optional[LocatorMatch],
        mc: MatchChain,
        doc: Document
    ) -> None:
        self.llm = llm
        self.clm = clm
        self.mc = mc
        self.doc = doc

    def __key__(self) -> Any:
        return (
            self.doc, self.clm.__key__(),
            self.llm.__key__() if self.llm else None,
        )

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, self.__class__) and other.__key__() == self.__key__()

    def __hash__(self) -> int:
        return hash(self.__key__())


class ScrContext(ConfigDataClass):
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
    abort: bool = False

    def __init__(self, blank: bool = False) -> None:
        super().__init__(blank)
        self.cookie_dict = {}
        self.match_chains = []
        self.docs = deque()
        self.defaults_mc = MatchChain(self, -1)
        self.origin_mc = MatchChain(self, -1, blank=True)
        # turn ctx to none temporarily for origin so it can be deepcopied
        self.origin_mc.ctx = None  # type: ignore


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
        filename: Optional[str],
        input_buffer_sizes: int = DEFAULT_RESPONSE_BUFFER_SIZE
    ) -> None:
        self._args_dict = content_match_build_format_args(
            cm, content, filename)
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

    def __init__(self, max_buffer_size: int = DEFAULT_MAX_PRINT_BUFFER_CAPACITY) -> None:
        self.lock = threading.Lock()
        self.printing_buffers = OrderedDict()
        self.finished_queues = set()
        self.size_limit = max_buffer_size
        self.size_blocked = threading.Condition(self.lock)

    def reset(self) -> None:
        self.active_id = 0
        self.dl_ids = 0
        self.main_thread_id = self.request_print_access()

    def main_thread_done(self) -> None:
        if self.main_thread_id is not None:
            self.declare_done(self.main_thread_id)
            self.main_thread_id = None

    def print(self, id: int, buffer: bytes) -> None:
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

    def request_print_access(self) -> int:
        with self.lock:
            id = self.dl_ids
            self.dl_ids += 1
            if id != self.active_id:
                self.printing_buffers[id] = []
        return id

    def declare_done(self, id: int) -> None:
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

    def flush(self, id: int) -> None:
        with self.lock:
            if not id != self.active_id:
                return
        sys.stdout.flush()


class PrintOutputStream:
    pom: PrintOutputManager
    id: int

    def __init__(self, pom: PrintOutputManager) -> None:
        self.pom = pom
        self.id = pom.request_print_access()

    def write(self, buffer: bytes) -> int:
        self.pom.print(self.id, buffer)
        return len(buffer)

    def flush(self) -> None:
        self.pom.flush(self.id)

    def close(self) -> None:
        self.pom.declare_done(self.id)


class DownloadStatusReport:
    name: str
    expected_size: Optional[int] = None
    downloaded_size: int = 0
    download_begin_time: datetime.datetime
    download_end_time: Optional[datetime.datetime] = None
    updates: deque[tuple[datetime.datetime, int]]
    download_finished: bool = False
    download_manager: 'DownloadManager'

    def __init__(self, download_manager: 'DownloadManager') -> None:
        self.updates = deque()
        self.download_manager = download_manager

    def gen_display_name(
        self,
        url: Optional[urllib.parse.ParseResult],
        filename: Optional[str],
        save_path: Optional[str]
    ) -> None:
        if save_path:
            if len(save_path) < DOWNLOAD_STATUS_NAME_LENGTH:
                self.name = save_path
                return
            self.name = os.path.basename(save_path)
        elif filename:
            self.name = filename
        elif url is not None:
            url_str = url.geturl()
            if len(url_str) < DOWNLOAD_STATUS_NAME_LENGTH:
                self.name = url_str
                return
            self.name = (
                "~~ "
                + url._replace(fragment="", scheme="", query="").geturl()
            )
        else:
            self.name = "<unnamed download>"
        self.name = truncate(
            self.name, DOWNLOAD_STATUS_NAME_LENGTH
        )

    def submit_update(self, received_filesize: int) -> None:
        time = datetime.datetime.now()
        with self.download_manager.status_report_lock:
            self.downloaded_size += received_filesize
            self.updates.append((time, self.downloaded_size))
            if len(self.updates) > DOWNLOAD_STATUS_NAME_LENGTH:
                self.updates.popleft()

    def enqueue(self) -> None:
        with self.download_manager.status_report_lock:
            self.download_manager.download_status_reports.append(self)
        self.download_begin_time = datetime.datetime.now()

    def finished(self) -> None:
        self.download_end_time = datetime.datetime.now()
        with self.download_manager.status_report_lock:
            self.download_finished = True


class DownloadJob:
    save_file: Optional[BinaryIO] = None
    temp_file: Optional[BinaryIO] = None
    temp_file_path: Optional[str] = None
    multipass_file: Optional[BinaryIO] = None
    print_stream: Optional[PrintOutputStream] = None
    content_stream: Union[BinaryIO, MinimalInputStream, None] = None
    content: Union[str, bytes, BinaryIO, MinimalInputStream, None] = None
    content_format: Optional[ContentFormat] = None
    filename: Optional[str] = None
    status_report: Optional[DownloadStatusReport] = None

    cm: ContentMatch
    save_path: Optional[str] = None
    context: str
    output_formatters: list[OutputFormatter]

    def __init__(self, cm: ContentMatch) -> None:
        self.cm = cm
        self.context = (
            f"{truncate(self.cm.doc.path)}{get_ci_di_context(self.cm)}"
        )
        self.output_formatters = []

    def requires_download(self) -> bool:
        return self.cm.mc.need_content and not self.cm.mc.content_raw

    def setup_print_stream(self, pom: 'PrintOutputManager') -> None:
        if self.cm.mc.content_print_format is not None:
            self.print_stream = PrintOutputStream(pom)

    def request_status_report(self, download_manager: 'DownloadManager') -> None:
        self.status_report = DownloadStatusReport(download_manager)

    def gen_fallback_filename(self) -> bool:
        if not self.cm.mc.need_filename or self.filename is not None:
            return True
        path = cast(urllib.parse.ParseResult, self.cm.url_parsed).path
        self.filename = sanitize_filename(urllib.parse.unquote(path))
        if self.filename is not None:
            return True
        try:
            self.filename = gen_final_content_format(
                cast(str, self.cm.mc.filename_default_format), self.cm, None
            ).decode("utf-8", errors="surrogateescape")
            return False
        except UnicodeDecodeError:
            log(
                self.cm.mc.ctx, Verbosity.ERROR,
                f"{self.cm.doc.path}{get_ci_di_context(self.cm)}: "
                + "generated default filename not valid utf-8"
            )
            return False

    def handle_save_path(self) -> InteractiveResult:
        if self.save_path is not None:
            # this was already done during for interactive filename determination
            return InteractiveResult.ACCEPT
        cm = self.cm
        if not cm.mc.content_save_format:
            return InteractiveResult.ACCEPT
        if cm.llm and not cm.mc.is_valid_label(cm.llm.result):
            log(cm.mc.ctx, Verbosity.WARN,
                f"matched label '{cm.llm.result}' would contain a slash, skipping this content from: {cm.doc.path}"
                )
            save_path = None
        if cm.mc.need_filename:
            if not self.fetch_content():
                return InteractiveResult.ERROR
        save_path_bytes = gen_final_content_format(
            cm.mc.content_save_format, cm, self.filename
        )
        try:
            save_path = save_path_bytes.decode(
                "utf-8", errors="surrogateescape"
            )
        except UnicodeDecodeError:
            log(
                cm.mc.ctx, Verbosity.ERROR,
                f"{cm.doc.path}{get_ci_di_context(cm)}: generated save path is not valid utf-8"
            )
            save_path = None
        while True:
            if save_path and not os.path.exists(os.path.dirname(os.path.abspath(save_path))):
                log(cm.mc.ctx, Verbosity.ERROR,
                    f"{cm.doc.path}{get_ci_di_context(cm)}: directory of generated save path does not exist"
                    )
                save_path = None
            if not save_path and not cm.mc.save_path_interactive:
                return InteractiveResult.ERROR
            if not cm.mc.save_path_interactive:
                break
            if save_path:
                res = prompt(
                    f'{cm.doc.path}{get_ci_di_context(cm)}: accept save path "{save_path}" [Yes/no/edit/chainskip/docskip]? ',
                    [
                        (InteractiveResult.ACCEPT, YES_INDICATING_STRINGS),
                        (InteractiveResult.REJECT, NO_INDICATING_STRINGS),
                        (InteractiveResult.EDIT, EDIT_INDICATING_STRINGS),
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
        if save_path is None:
            return InteractiveResult.REJECT
        self.save_path = save_path
        return InteractiveResult.ACCEPT

    def selenium_download_from_local_file(self) -> bool:
        self.content = self.cm.clm.result
        self.content_format = ContentFormat.FILE
        self.filename = os.path.basename(self.cm.clm.result)
        return True

    def selenium_download_external(self) -> bool:
        proxies = None
        if self.cm.mc.ctx.selenium_variant == SeleniumVariant.TORBROWSER:
            tbdriver = cast(TorBrowserDriver, self.cm.mc.ctx.selenium_driver)
            proxies = {
                "http": f"socks5h://localhost:{tbdriver.socks_port}",
                "https": f"socks5h://localhost:{tbdriver.socks_port}",
                "data": None
            }
        try:
            try:
                req = request_raw(
                    self.cm.mc.ctx, self.cm.clm.result, cast(
                        urllib.parse.ParseResult, self.cm.url_parsed),
                    load_selenium_cookies(self.cm.mc.ctx),
                    proxies=proxies, stream=True
                )
                self.content = ResponseStreamWrapper(req)
                self.content_format = ContentFormat.STREAM
                self.filename = request_try_get_filename(req)
                return True
            except requests.exceptions.RequestException as ex:
                raise request_exception_to_scr_fetch_error(ex)
        except ScrFetchError as ex:
            log(
                self.cm.mc.ctx, Verbosity.ERROR,
                f"{truncate(self.cm.doc.path)}{get_ci_di_context(self.cm)}: "
                + f"failed to download '{truncate(self.cm.clm.result)}': {str(ex)}"
            )
            return False

    def selenium_download_internal(self) -> bool:
        doc_url_str = selenium_get_url(self.cm.mc.ctx)
        if doc_url_str is None:
            return False
        doc_url = urllib.parse.urlparse(doc_url_str)

        if doc_url.netloc != cast(urllib.parse.ParseResult, self.cm.url_parsed).netloc:
            log(
                self.cm.mc.ctx, Verbosity.ERROR,
                f"{self.cm.clm.result}{get_ci_di_context(self.cm)}: "
                + f"failed to download: seldl=internal does not work across origins"
            )
            return False

        tmp_path, tmp_filename = gen_dl_temp_name(self.cm.mc.ctx, None)
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
            selenium_exec_script(self.cm.mc.ctx, script_source,
                                 self.cm.clm.result, tmp_filename)
        except SeleniumWebDriverException as ex:
            if selenium_has_died(self.cm.mc.ctx):
                report_selenium_died(self.cm.mc.ctx)
            else:
                log(
                    self.cm.mc.ctx, Verbosity.ERROR,
                    f"{self.cm.clm.result}{get_ci_di_context(self.cm)}: "
                    + f"selenium download failed: {str(ex)}"
                )
            return False
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
                    if selenium_has_died(self.cm.mc.ctx):
                        return False

            i += 1
        self.content = tmp_path
        self.content_format = ContentFormat.TEMP_FILE
        # TODO: maybe support filenames here ?
        return True

    def selenium_download_fetch(self) -> bool:
        script_source = """
            const url = arguments[0];
            var content_disposition = null;
            return (async () => {
                return await fetch(url, {
                    method: 'GET',
                })
                .then(res => {
                    content_disposition = res.headers.get(
                        'Content-Disposition');
                    return res.blob();
                })
                .then((blob, cd) => new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.readAsDataURL(blob);
                    reader.onload = () => (resolve(reader.result.substr(reader.result.indexOf(',') + 1)), cd);
                    reader.onerror = error => reject(error);
                }))
                .then(result => {
                    return {
                        "ok": result,
                        "content_disposition": content_disposition,
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
        driver = cast(SeleniumWebDriver, self.cm.mc.ctx.selenium_driver)
        try:
            doc_url = driver.current_url
            res = selenium_exec_script(
                self.cm.mc.ctx, script_source, self.cm.clm.result)
        except SeleniumWebDriverException as ex:
            if selenium_has_died(self.cm.mc.ctx):
                report_selenium_died(self.cm.mc.ctx)
                return False
            err = str(ex)
        if "error" in res:
            err = res["error"]
        if err is not None:
            cors_warn = ""
            if urllib.parse.urlparse(doc_url).netloc != urllib.parse.urlparse(self.cm.clm.result).netloc:
                cors_warn = " (potential CORS issue)"
            log(
                self.cm.mc.ctx, Verbosity.ERROR,
                f"{truncate(self.cm.doc.path)}{get_ci_di_context(self.cm)}: "
                + f"selenium download of '{self.cm.clm.result}' failed{cors_warn}: {err}"
            )
            return False
        self.content = binascii.a2b_base64(res["ok"])
        if self.status_report:
            self.status_report.expected_size = len(self.content)
        self.filename = try_get_filename_from_content_disposition(
            res.get("content_disposition", "")
        )
        self.content_format = ContentFormat.BYTES
        return True

    def selenium_download(self) -> bool:
        if (
            self.cm.doc.document_type == DocumentType.FILE
            and cast(urllib.parse.ParseResult, self.cm.url_parsed).scheme in ["", "file"]
        ):
            return self.selenium_download_from_local_file()

        if self.cm.mc.selenium_download_strategy == SeleniumDownloadStrategy.EXTERNAL:
            return self.selenium_download_external()

        if self.cm.mc.selenium_download_strategy == SeleniumDownloadStrategy.INTERNAL:
            return self.selenium_download_internal()

        assert self.cm.mc.selenium_download_strategy == SeleniumDownloadStrategy.FETCH

        return self.selenium_download_fetch()

    def fetch_content(self) -> bool:
        if self.content_format is not None:
            # this was already done during filename determination
            return True
        if self.cm.mc.content_raw:
            self.content = self.cm.clm.result
            self.content_format = ContentFormat.STRING
        else:
            if not self.cm.mc.need_content:
                self.content_format = ContentFormat.UNNEEDED
            else:
                if self.cm.mc.ctx.selenium_variant.enabled():
                    if not self.selenium_download():
                        return False
                else:
                    data = try_read_data_url(self.cm)
                    if data is not None:
                        self.content = data
                        self.content_format = ContentFormat.BYTES
                        if self.status_report:
                            self.status_report.expected_size = len(data)
                    elif self.cm.doc.document_type.derived_type() is DocumentType.FILE:
                        self.content = self.cm.clm.result
                        self.content_format = ContentFormat.FILE
                        if self.status_report:
                            try:
                                self.status_report.expected_size = os.path.getsize(
                                    self.content)
                            except IOError:
                                pass
                    else:
                        try:
                            res = request_raw(
                                self.cm.mc.ctx, self.cm.clm.result,
                                cast(urllib.parse.ParseResult,
                                     self.cm.url_parsed),
                                stream=True
                            )
                            self.content = ResponseStreamWrapper(res)
                            self.filename = request_try_get_filename(res)
                            if self.status_report:
                                self.status_report.expected_size = (
                                    request_try_get_filesize(res)
                                )
                            self.content_format = ContentFormat.STREAM
                        except requests.exceptions.RequestException as ex:
                            fe = request_exception_to_scr_fetch_error(ex)
                            log(self.cm.mc.ctx, Verbosity.ERROR,
                                f"{self.context}: failed to download '{truncate(self.cm.clm.result)}': {str(fe)}")
                            return False
        if not self.gen_fallback_filename():
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
            self.cm, save_file, self.content, self.filename
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
        except ScrFetchError as ex:
            log(self.cm.mc.ctx, Verbosity.ERROR,
                f"{self.context}: failed to open file '{truncate(self.content)}': {str(ex)}")
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
            stream, self.content, self.filename
        ))
        return True

    def check_abort(self) -> None:
        if self.cm.mc.ctx.abort:
            raise InterruptedError

    def run_job(self) -> bool:
        if self.status_report:
            self.status_report.gen_display_name(
                self.cm.url_parsed, self.filename, self.save_path
            )
            self.status_report.enqueue()
        success = False
        try:
            if self.handle_save_path() != InteractiveResult.ACCEPT:
                return False
            if not self.fetch_content():
                return False

            self.check_abort()
            self.content_stream: Union[BinaryIO, MinimalInputStream, None] = (
                cast(Union[BinaryIO, MinimalInputStream], self.content)
                if self.content_format == ContentFormat.STREAM
                else None
            )

            if not self.setup_content_file():
                return False
            if not self.setup_save_file():
                return False
            if self.status_report:
                # try to generate a better name now that we have more information
                self.status_report.gen_display_name(
                    self.cm.url_parsed, self.filename, self.save_path
                )
            if not self.setup_print_output():
                return False
            self.check_abort()

            if self.content_stream is None:
                for of in self.output_formatters:
                    res = of.advance()
                    assert res == False
                    self.check_abort()
                success = True
                return True

            if self.cm.mc.need_output_multipass and self.multipass_file is None:
                try:
                    self.temp_file_path, _filename = gen_dl_temp_name(
                        self.cm.mc.ctx, self.save_path)
                    self.temp_file = open(self.temp_file_path, "xb+")
                except IOError as ex:
                    return False
                self.multipass_file = self.temp_file
                self.check_abort()

            if self.content_stream is not None:
                while True:
                    buf = self.content_stream.read(
                        DEFAULT_RESPONSE_BUFFER_SIZE
                    )
                    self.check_abort()
                    if self.status_report:
                        self.status_report.submit_update(len(buf))
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
                        self.check_abort()
                        advance_output_formatters(self.output_formatters, buf)
                        if len(buf) < DEFAULT_RESPONSE_BUFFER_SIZE:
                            break
            success = True
            return True
        except InterruptedError:
            return False
        finally:
            if self.status_report:
                self.status_report.finished()
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
            path = self.cm.clm.result
            if self.requires_download():
                log(self.cm.mc.ctx, Verbosity.DEBUG,
                    f"finished downloading {path}" if success else f"failed to download {path}"
                    )


class StatusReportLine:
    name: str
    expected_size: Optional[int]
    downloaded_size: int
    speed_calculatable: bool
    download_begin: datetime.datetime
    download_end: Optional[datetime.datetime]
    speed_frame_time_begin: datetime.datetime
    speed_frame_time_end: datetime.datetime
    speed_frame_size_begin: int
    speed_frame_size_end: int
    star_pos: int = 1
    star_dir: int = 1
    last_line_length: int = 0
    finished: bool = False

    total_time_str: str
    total_time_u_str: str
    bar_str: str
    downloaded_size_str: str
    downloaded_size_u_str: str
    expected_size_str: str
    expected_size_u_str: str
    speed_str: str
    speed_u_str: str
    eta_str: str
    eta_u_str: str


BYTE_SIZE_STRING_LEN_MAX = 10


def get_byte_size_string(size: Union[int, float]) -> tuple[str, str]:
    if size < 2**10:
        if type(size) is int:
            return f"{size}", "B"
        return f"{size:.2f}", "B"
    units = ["K", "M", "G", "T", "P", "E", "Z", "Y"]
    unit = int(math.log(size, 1024))
    if unit >= len(units):
        unit = len(units) - 1
    return f"{float(size)/2**(10 * unit):.2f}", f"{units[unit - 1]}iB"


TIMESPAN_STRING_LEN_MAX = 10


def get_timespan_string(ts: float) -> tuple[str, str]:
    if ts < 60:
        return f"{ts:.1f}", "s"
    if ts < 3600:
        return f"{int(ts / 60):02}:{int(ts % 60):02}", "m"
    return f"{int(ts / 3600):02}:{int((ts % 3600) / 60):02}:{int(ts % 60):02}", "h"


def lpad(string: str, tgt_len: int, min_pad: int = 0) -> str:
    return " " * (tgt_len - len(string) + min_pad) + string


def rpad(string: str, tgt_len: int, min_pad: int = 0) -> str:
    return string + " " * (tgt_len - len(string) + min_pad)


class DownloadManager:
    ctx: ScrContext
    max_threads: int
    pending_jobs: set[concurrent.futures.Future[bool]]
    pom: PrintOutputManager
    executor: concurrent.futures.ThreadPoolExecutor
    status_report_lock: threading.Lock
    download_status_reports: list[DownloadStatusReport]
    enable_status_reports: bool

    def __init__(self, ctx: ScrContext, max_threads: int, enable_status_reports: bool) -> None:
        self.ctx = ctx
        self.pending_jobs = set()
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_threads
        )
        self.pom = PrintOutputManager()
        self.status_report_lock = threading.Lock()
        self.download_status_reports = []
        self.enable_status_reports = enable_status_reports

    def submit(self, dj: DownloadJob) -> None:
        log(
            self.ctx, Verbosity.DEBUG,
            f"enqueuing download for {dj.cm.clm.result}"
        )
        dj.setup_print_stream(self.pom)
        if self.enable_status_reports:
            dj.request_status_report(self)
        self.pending_jobs.add(self.executor.submit(dj.run_job))

    def load_status_report_lines(self, report_lines: list[StatusReportLine]) -> None:
        with self.status_report_lock:
            # when we have more reports than report lines,
            # we remove the oldest finished report
            # if none are finished, we get more report lines
            if len(self.download_status_reports) > len(report_lines):
                i = 0
                while i < len(self.download_status_reports):
                    if self.download_status_reports[i].download_finished:
                        del self.download_status_reports[i]
                        if len(self.download_status_reports) == len(report_lines):
                            break
                    else:
                        i += 1
                else:
                    for i in range(len(self.download_status_reports) - len(report_lines)):
                        report_lines.append(StatusReportLine())
            for i in range(len(report_lines)):
                rl = report_lines[i]
                dsr = self.download_status_reports[i]
                rl.name = dsr.name
                rl.expected_size = dsr.expected_size
                rl.downloaded_size = dsr.downloaded_size
                rl.download_begin = dsr.download_begin_time
                rl.download_end = dsr.download_end_time
                rl.finished = dsr.download_finished
                if not len(dsr.updates):
                    rl.speed_calculatable = False
                elif len(dsr.updates) == 1:
                    rl.speed_calculatable = True
                    rl.speed_frame_time_begin = dsr.download_begin_time
                    rl.speed_frame_size_begin = 0
                    rl.speed_frame_time_end = dsr.updates[0][0]
                    rl.speed_frame_size_end = dsr.updates[0][1]
                else:
                    rl.speed_calculatable = True
                    rl.speed_frame_time_begin = dsr.updates[0][0]
                    rl.speed_frame_size_begin = dsr.updates[0][1]
                    rl.speed_frame_time_end = dsr.updates[-1][0]
                    rl.speed_frame_size_end = dsr.updates[-1][1]

    def stringify_status_report_lines(self, report_lines: list[StatusReportLine]) -> None:
        now = datetime.datetime.now()
        for rl in report_lines:
            if rl.finished:
                rl.expected_size = rl.downloaded_size
            if rl.expected_size and rl.expected_size >= rl.downloaded_size:
                frac = float(rl.downloaded_size) / rl.expected_size
                filled = int(frac * (DOWNLOAD_STATUS_BAR_LENGTH - 1))
                empty = DOWNLOAD_STATUS_BAR_LENGTH - filled - 1
                tip = ">" if rl.downloaded_size != rl.expected_size else "="
                rl.bar_str = "[" + "=" * filled + tip + " " * empty + "]"
            else:
                left = rl.star_pos - 1
                right = DOWNLOAD_STATUS_BAR_LENGTH - 3 - left
                rl.bar_str = "[" + " " * left + "***" + " " * right + "]"
                if rl.star_pos == DOWNLOAD_STATUS_BAR_LENGTH - 2:
                    rl.star_dir = -1
                elif rl.star_pos == 1:
                    rl.star_dir = 1
                rl.star_pos += rl.star_dir
            rl.downloaded_size_str, rl.downloaded_size_u_str = (
                get_byte_size_string(rl.downloaded_size)
            )
            if rl.expected_size:
                rl.expected_size_str, rl.expected_size_u_str = (
                    get_byte_size_string(rl.expected_size)
                )
            else:
                rl.expected_size_str, rl.expected_size_u_str = "???", "B"

            if rl.finished:
                assert rl.download_end
                rl.speed_frame_size_begin = 0
                rl.speed_frame_time_begin = rl.download_begin
                rl.speed_frame_size_end = rl.downloaded_size
                rl.speed_frame_time_end = rl.download_end
                rl.speed_calculatable = True
            else:
                rl.download_end = now
            if rl.speed_calculatable:
                duration = (
                    (rl.speed_frame_time_end -
                        rl.speed_frame_time_begin).total_seconds()
                )
                handled_size = rl.speed_frame_size_end - rl.speed_frame_size_begin
                if handled_size == 0:
                    speed = 0.0
                    rl.eta_str, rl.eta_u_str = "", ""
                else:
                    speed = float(handled_size) / duration
                    if rl.expected_size and rl.expected_size > rl.downloaded_size:
                        rl.eta_str, rl.eta_u_str = get_timespan_string(
                            (rl.expected_size - rl.downloaded_size) / speed
                        )
                    else:
                        rl.eta_str, rl.eta_u_str = "", ""
                rl.speed_str, rl.speed_u_str = get_byte_size_string(speed)
                rl.speed_u_str += "/s"
            else:
                rl.speed_frame_time_end = now
                rl.eta_str, rl.eta_u_str = "", ""
                rl.speed_str, rl.speed_u_str = "???", "B/s"

            rl.total_time_str, rl.total_time_u_str = get_timespan_string(
                (rl.download_end - rl.download_begin).total_seconds()
            )

    def append_status_report_lines_to_string(self, report_lines: list[StatusReportLine], report: str) -> str:
        def field_len_max(field_name: str) -> int:
            return max(map(lambda rl: len(rl.__dict__[field_name]), report_lines))

        name_lm = field_len_max("name")
        total_time_lm = field_len_max("total_time_str")
        total_time_u_lm = field_len_max("total_time_u_str")
        downloaded_size_lm = field_len_max("downloaded_size_str")
        downloaded_size_u_lm = field_len_max("downloaded_size_u_str")
        expected_size_lm = field_len_max("expected_size_str")
        expected_size_u_lm = field_len_max("expected_size_u_str")
        eta_lm = field_len_max("eta_str")
        eta_u_lm = field_len_max("eta_u_str")
        speed_lm = field_len_max("speed_str")
        speed_u_lm = field_len_max("speed_u_str")

        for rl in report_lines:
            line = rpad(rl.name, name_lm, 1)
            line += lpad(rl.total_time_str, total_time_lm) + " "
            line += rpad(rl.total_time_u_str, total_time_u_lm, 1)
            line += rl.bar_str
            line += lpad(rl.downloaded_size_str, downloaded_size_lm, 1) + " "
            line += rpad(rl.downloaded_size_u_str, downloaded_size_u_lm, 1)
            line += "/"
            line += lpad(rl.expected_size_str, expected_size_lm, 1) + " "
            line += rpad(rl.expected_size_u_str, expected_size_u_lm, 2)
            line += lpad(rl.speed_str, speed_lm) + " "
            line += rpad(rl.speed_u_str, speed_u_lm)
            if rl.eta_str:
                line += "  eta "
                line += lpad(rl.eta_str, eta_lm) + " "
                line += lpad(rl.eta_u_str, eta_u_lm)

            if len(line) < rl.last_line_length:
                lll = len(line)
                # fill with spaces to clear previous line
                line += " " * (rl.last_line_length - lll)
                rl.last_line_length = lll
            else:
                rl.last_line_length = len(line)
            report += line + "\n"
        return report

    def wait_until_jobs_done(self) -> None:
        if not self.enable_status_reports:
            results = concurrent.futures.wait(self.pending_jobs)
            for x in results.done:
                x.result()
            self.pending_jobs.clear()

        committed_report_line_count = 0
        report_lines: list[StatusReportLine] = []
        while True:
            results = concurrent.futures.wait(
                self.pending_jobs,
                timeout=0 if not committed_report_line_count else DOWNLOAD_STATUS_REFRESH_INTERVAL
            )
            for x in results.done:
                x.result()
            self.pending_jobs = results.not_done
            if not self.pending_jobs:
                # otherwise print one more report so everything is displayed as done
                if not committed_report_line_count:
                    break
            self.load_status_report_lines(report_lines)
            if len(report_lines) == 0:
                continue
            self.stringify_status_report_lines(report_lines)
            report = ""
            if committed_report_line_count:
                report += f"\x1B[{committed_report_line_count}A"
            report = self.append_status_report_lines_to_string(
                report_lines, report)
            committed_report_line_count = len(report_lines)
            sys.stdout.write(report)
            if not self.pending_jobs:
                break

    def terminate(self, cancel_running: bool = False) -> None:
        try:
            if not cancel_running:
                cancel_running = True
                self.wait_until_jobs_done()
                cancel_running = False
        finally:
            if cancel_running:
                self.ctx.abort = True
            self.executor.shutdown(wait=True, cancel_futures=cancel_running)


def abort_on_broken_pipe() -> None:
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


def apply_general_format_args(doc: Document, mc: MatchChain, args_dict: dict[str, Any], unstable_ci: bool = False) -> None:
    dict_update_unless_none(args_dict, {
        "cenc": doc.encoding,
        "cesc": mc.content_escape_sequence,
        "dl":   doc.path,
        "chain": mc.chain_id,
        "di": mc.di,
        "ci": mc.ci if not unstable_ci else None
    })


def apply_locator_match_format_args(locator_name: str, lm: LocatorMatch, args_dict: dict[str, Any]) -> None:
    p = locator_name[0]
    dict_update_unless_none(args_dict, {
        f"{p}x": lm.xmatch,
        f"{p}r": lm.rmatch,
        f"{p}f": lm.fres,
        f"{p}js": lm.jsres,
        f"{p}{'m' if p == 'c' else ''}": lm.result,
    })
    # apply the unnamed groups first in case somebody overwrote it with a named group
    args_dict.update(lm.unnamed_group_list_to_dict(f"{p}g"))

    # finally apply the named groups
    if lm.named_cgroups:
        args_dict.update(lm.named_cgroups)


def apply_filename_format_args(filename: Optional[str], args_dict: dict[str, Any]) -> None:
    if filename is None:
        return
    b, e = os.path.splitext(filename)
    args_dict.update({
        "fn": filename,
        "fb": b,
        "fe": e,
    })


def content_match_build_format_args(
    cm: ContentMatch,
    content: Union[str, bytes, MinimalInputStream, BinaryIO, None] = None,
    filename: Optional[str] = None
) -> dict[str, Any]:
    args_dict: dict[str, Any] = {}
    apply_general_format_args(cm.doc, cm.mc, args_dict)
    apply_filename_format_args(filename, args_dict)
    if content is not None:
        args_dict["c"] = content

    potential_locator_matches = [
        ("d", cm.doc.locator_match),
        ("l", cm.llm),
        ("c", cm.clm)
    ]
    # remove None regex matches (and type cast this to make mypy happy)
    locator_matches = cast(
        list[tuple[str, LocatorMatch]],
        list(filter(lambda plm: plm[1] is not None, potential_locator_matches))
    )

    for loc_name, loc_match in locator_matches:
        apply_locator_match_format_args(loc_name, loc_match, args_dict)

    return args_dict


def log_raw(verbosity: Verbosity, msg: str) -> None:
    sys.stderr.write(verbosities_display_dict[verbosity] + msg + "\n")


BSE_U_REGEX_MATCH = re.compile("[0-9A-Fa-f]{4}")


def parse_bse_u(match: re.Match[str]) -> str:
    code = match[3]
    if not BSE_U_REGEX_MATCH.match(code):
        raise ValueError(f"invalid escape code \\u{code}")
    code = (b"\\u" + code.encode("ascii")).decode("unicodeescape")
    return "".join(map(lambda x: cast(str, x) if x else "", [match[1], match[2], code]))


BSE_X_REGEX_MATCH = re.compile("[0-9A-Fa-f]{2}")


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
            raise ValueError(f"unterminated escape sequence '\\'")
        raise ValueError(f"invalid escape code \\{code}")
    return "".join(map(lambda x: cast(str, x) if x else "", [match[1], match[2], res]))


BACKSLASHESCAPE_PATTERNS = [
    (re.compile(r"(^|[^\\])(\\\\)*\\u(.{0,4})"), parse_bse_u),
    (re.compile(r"(^|[^\\])(\\\\)*\\x(.{0,2})"), parse_bse_x),
    (re.compile(
        "(^|[^\\\\])(\\\\\\\\)*\\\\([rntfb\\'\\\"\\\\]|$)"), parse_bse_o),
]


def unescape_string(txt: str) -> str:
    for regex, parser in BACKSLASHESCAPE_PATTERNS:
        txt = regex.sub(parser, txt)
    return txt


def log(ctx: ScrContext, verbosity: Verbosity, msg: str) -> None:
    if verbosity == Verbosity.ERROR:
        ctx.error_code = 1
    if ctx.verbosity is None or ctx.verbosity >= verbosity:
        log_raw(verbosity, msg)


def help(err: bool = False) -> None:
    global DEFAULT_CPF
    global DEFAULT_CWF
    text = f"""{SCRIPT_NAME} [OPTIONS]
    Extract content from urls or files by specifying content matching chains
    (xpath -> regex -> python format string).

    Content to Write out:
        cx=<xpath>           xpath for content matching
        cr=<regex>           regex for content matching
        cf=<format string>   content format string (args: <cr capture groups>, xmatch, rmatch, di, ci)
        cjs=<js string>      javascript to execute on the page, format args are available as js variables (selenium only)
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
        ljs=<js string>      javascript to execute on the page, format args are available as js variables (selenium only)
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
        djs=<js string>     javascript to execute on the page, format args are available as js variables (selenium only)
        dimin=<number>      initial document index, each successful match gets one index
        dimax=<number>      max document index, matching stops here
        dmm=<bool>          allow multiple document matches in one document instead of picking the first
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
        selstrat=<strategy> matching strategy for selenium (default: plain, values: anymatch, plain, interactive, deduplicate)
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
        {{cjs}}               output of cjs
        {{cm}}                final content match after link normalization (cl) and user interaction (cin)
        {{c}}                 content, downloaded from cm in case of cl, otherwise equal to cm

        {{lx}}                label xpath match
        {{lr}}                label regex match, equal to {{lx}} if lr is unspecified
        <lr capture groups> the named regex capture groups (?P<name>...) from cr are available as {{name}},
                            the unnamed ones (...) as {{lg<unnamed capture group number>}}
        {{lf}}                label after applying lf
        {{ljs}}               output of ljs
        {{l}}                 final label after user interaction (lin)

        {{dx}}                document link xpath match
        {{dr}}                document link regex match, equal to {{dx}} if dr is unspecified
        <dr capture groups> the named regex capture groups (?P<name>...) from dr are available as {{name}},
                            the unnamed ones (...) as {{dg<unnamed capture group number>}}
        {{df}}                document link after applying df
        {{djs}}               output of djs
        {{d}}                 final document link after user interaction (din)

        {{di}}                document index
        {{ci}}                content index
        {{dl}}                document link (inside df, this refers to the parent document)
        {{cenc}}              content encoding, deduced while respecting cenc and cfenc
        {{cesc}}              escape sequence for separating content, can be overwritten using cesc
        {{chain}}             id of the match chain that generated this content

        {{fn}}                filename from the url of a cm with cl
        {{fb}}                basename component of {{fn}} (extension stripped away)
        {{fe}}                extension component of {{fn}}, including the dot (empty string if there is no extension)


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
        sel=<browser|bool>  use selenium (default is firefox) to load urls into an interactive browser session
                            (default: disabled, values: tor, chrome, firefox, disabled)
        tbdir=<path>        root directory of the tor browser installation, implies sel=tor
                            (default: environment variable TOR_BROWSER_DIR)
        mt=<int>            maximum threads for background downloads, 0 to disable. defaults to cpu core count
        repl=<bool>         accept commands in a read eval print loop
        exit=<bool>         exit the repl (with the result of the current command)
        """.strip()
    if err:
        sys.stderr.write(text + "\n")
        sys.exit(1)

    else:
        print(text)


def get_script_dir() -> str:
    return os.path.dirname(os.path.abspath(os.path.realpath(__file__)))


def add_script_dir_to_path() -> None:
    os.environ["PATH"] = get_script_dir() + ":" + os.environ["PATH"]


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
    ctx: ScrContext
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


def setup_selenium_tor(ctx: ScrContext) -> None:
    # use bundled geckodriver if available
    cwd = os.getcwd()
    add_script_dir_to_path()
    if ctx.tor_browser_dir is None:
        tb_env_var = "TOR_BROWSER_DIR"
        if tb_env_var in os.environ:
            ctx.tor_browser_dir = os.environ[tb_env_var]
        else:
            raise ScrSetupError(f"no tbdir specified, check --help")
    try:
        ctx.selenium_driver = TorBrowserDriver(
            ctx.tor_browser_dir, tbb_logfile_path=ctx.selenium_log_path,
            options=selenium_build_firefox_options(ctx)
        )

    except SeleniumWebDriverException as ex:
        raise ScrSetupError(f"failed to start tor browser: {str(ex)}")
    os.chdir(cwd)  # restore cwd that is changed by tor for some reason


def setup_selenium_firefox(ctx: ScrContext) -> None:
    # use bundled geckodriver if available
    add_script_dir_to_path()
    try:
        ctx.selenium_driver = selenium.webdriver.Firefox(
            options=selenium_build_firefox_options(ctx),
            service=SeleniumFirefoxService(
                log_path=ctx.selenium_log_path),  # type: ignore
        )
    except SeleniumWebDriverException as ex:
        ex_msg = str(ex).strip('\n ')
        raise ScrSetupError(
            f"failed to start geckodriver: {ex_msg}\n" +
            f"    consider {SCRIPT_NAME} --install-geckodriver"
        )


def setup_selenium_chrome(ctx: ScrContext) -> None:
    # allow usage of bundled chromedriver
    add_script_dir_to_path()
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
        raise ScrSetupError(f"failed to start chromedriver: {str(ex)}")


def selenium_add_cookies_through_get(ctx: ScrContext) -> None:
    # ctx.selenium_driver.set_page_load_timeout(0.01)
    assert ctx.selenium_driver is not None
    for domain, cookies in ctx.cookie_dict.items():
        try:
            ctx.selenium_driver.get(f"https://{domain}")
        except SeleniumTimeoutException:
            log(
                ctx, Verbosity.WARN,
                "Failed to apply cookies for https://{domain}: page failed to load"
            )
        for c in cookies.values():
            ctx.selenium_driver.add_cookie(c)


def selenium_start_wrapper(*args: Any, **kwargs: Any) -> None:
    def preexec_function() -> None:
        # this makes sure that the selenium instance does not die on SIGINT
        os.setpgrp()
    original_p_open = subprocess.Popen
    subprocess.Popen = functools.partial(  # type: ignore
        subprocess.Popen, preexec_fn=preexec_function
    )
    try:
        selenium_start_wrapper.original_start(*args, **kwargs)  # type: ignore
    finally:
        subprocess.Popen = original_p_open  # type: ignore


def prevent_selenium_sigint() -> None:
    if selenium.webdriver.common.service.Service.start is selenium_start_wrapper:
        return
    selenium_start_wrapper.original_start = selenium.webdriver.common.service.Service.start  # type: ignore
    selenium.webdriver.common.service.Service.start = selenium_start_wrapper  # type: ignore


def selenium_exec_script(ctx: ScrContext, script: str, *args: Any) -> Any:
    assert ctx.selenium_driver is not None
    # execute_script is not annotated -> we have to eat the type error
    return ctx.selenium_driver.execute_script(script, *args)  # type: ignore


def setup_selenium(ctx: ScrContext) -> None:
    if ctx.repl:
        prevent_selenium_sigint()
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
        ctx.user_agent = str(selenium_exec_script(
            ctx, "return navigator.userAgent;"))

    ctx.selenium_driver.set_page_load_timeout(ctx.request_timeout_seconds)
    if ctx.cookie_jar:
        # todo: implement something more clever for this, at least for chrome:
        # https://stackoverflow.com/questions/63220248/how-to-preload-cookies-before-first-request-with-python3-selenium-chrome-webdri
        selenium_add_cookies_through_get(ctx)


def get_format_string_keys(fmt_string: str) -> list[str]:
    return [f for (_, f, _, _) in Formatter().parse(fmt_string) if f is not None]


def format_string_arg_occurence(fmt_string: Optional[str], arg_name: str) -> int:
    if fmt_string is None:
        return 0
    fmt_args = get_format_string_keys(fmt_string)
    return fmt_args.count(arg_name)


def format_string_args_occurence(
    fmt_string: Optional[str], arg_names: list[str]
) -> int:
    if fmt_string is None:
        return 0
    count = 0
    fmt_args = get_format_string_keys(fmt_string)
    for an in arg_names:
        count += fmt_args.count(an)
    return count


def format_strings_args_occurence(
    fmt_strings: list[Optional[str]],
    arg_names: list[str]
) -> int:
    count = 0
    for f in fmt_strings:
        count += format_string_args_occurence(f, arg_names)
    return count


def validate_format(
    conf: ConfigDataClass, attrib_path: list[str], dummy_cm: ContentMatch,
    unescape: bool, has_content: bool = False, has_filename: bool = False
) -> None:
    try:
        known_keys = content_match_build_format_args(
            dummy_cm, "" if has_content else None, "" if has_filename else None
        )
        unnamed_key_count = 0
        fmt_keys = get_format_string_keys(conf.resolve_attrib_path(
            attrib_path,
            unescape_string if unescape else None
        ))
        named_arg_count = 0
        for k in fmt_keys:
            if k == "":
                named_arg_count += 1
                if named_arg_count > unnamed_key_count:
                    raise ScrSetupError(
                        f"exceeded number of ordered keys in {conf.get_configuring_argument(attrib_path)}"
                    )
            elif k not in known_keys:
                raise ScrSetupError(
                    f"unavailable key '{{{k}}}' in {conf.get_configuring_argument(attrib_path)}"
                )
    except (re.error, ValueError) as ex:
        raise ScrSetupError(
            f"{str(ex)} in {conf.get_configuring_argument(attrib_path)}"
        )

# we need ctx because mc.ctx is stil None before we apply_defaults


def gen_default_format(mc: MatchChain) -> str:
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
    return form


def setup_match_chain(mc: MatchChain, ctx: ScrContext, special_args_occured: bool = False) -> None:

    mc.apply_defaults(ctx.defaults_mc)
    mc.ci = mc.cimin
    mc.di = mc.dimin

    if mc.dimin > mc.dimax:
        raise ScrSetupError(f"dimin can't exceed dimax")
    if mc.cimin > mc.cimax:
        raise ScrSetupError(f"cimin can't exceed cimax")

    if mc.content_write_format is not None and mc.content_save_format is None:
        mc.content_save_format = DEFAULT_CSF

    if not mc.document_output_chains:
        mc.document_output_chains = [mc]

    if mc.save_path_interactive and mc.content_save_format is not None:
        mc.content_save_format = ""

    locators = [mc.content, mc.label, mc.document]
    for l in locators:
        l.setup(mc)

    mc.has_xpath_matching = any(l.xpath is not None for l in locators)
    mc.has_label_matching = mc.label.is_active()
    mc.has_content_xpaths = mc.labels_inside_content is not None and mc.label.xpath is not None
    mc.has_document_matching = mc.document.is_active()
    mc.has_content_matching = mc.has_label_matching or mc.content.is_active()
    mc.has_interactive_matching = mc.label.interactive or mc.content.interactive

    if mc.content_print_format or mc.content_save_format:
        mc.has_content_matching = True

    if mc.has_content_matching and mc.content_print_format is None and mc.content_save_format is None:
        mc.content_print_format = DEFAULT_CPF

    dummy_cm = mc.gen_dummy_content_match()
    if mc.content_print_format:
        validate_format(mc, ["content_print_format"],
                        dummy_cm, True, True, not mc.content_raw)

    if mc.content_save_format is not None:
        if mc.content_save_format == "":
            raise ScrSetupError(
                f"csf cannot be the empty string: {mc.get_configuring_argument(['content_save_format'])}"
            )
        validate_format(mc, ["content_save_format"], dummy_cm,
                        True, False, not mc.content_raw)
        if mc.content_write_format is None:
            mc.content_write_format = DEFAULT_CWF
        else:
            validate_format(mc, ["content_write_format"],
                            dummy_cm, True, True, not mc.content_raw)

    if not mc.has_label_matching:
        mc.label_allow_missing = True
        if mc.labels_inside_content:
            raise ScrSetupError(
                f"match chain {mc.chain_id}: cannot specify lic without lx or lr"
            )
    default_format: Optional[str] = None

    output_formats = [
        mc.content_print_format,
        mc.content_save_format,
        mc.content_write_format  # this is none if save is None
    ]

    mc.need_filename = format_strings_args_occurence(
        output_formats,
        ["fn", "fb", "fe"]
    ) > 0

    mc.need_content = format_strings_args_occurence(
        output_formats, ["c"]
    ) > 0

    mc.need_label = format_strings_args_occurence(
        output_formats, ["l"]
    ) > 0

    mc.need_output_multipass = any(
        format_string_arg_occurence(of, "c") for of in output_formats
    )

    if mc.filename_default_format is None:
        if mc.need_filename:
            default_format = gen_default_format(mc)
            mc.filename_default_format = default_format + ".dat"
    else:
        validate_format(
            mc, ["filename_default_format"],
            dummy_cm, True, False, False
        )

    if mc.label_default_format is None:
        if mc.label_allow_missing and mc.need_label:
            if default_format is None:
                default_format = gen_default_format(mc)
            mc.label_default_format = default_format
    else:
        validate_format(
            mc, ["label_default_format"],
            dummy_cm, True, False, False
        )
    if not mc.has_content_matching and not mc.has_document_matching:
        if not (mc.chain_id == 0 and (mc.ctx.repl or special_args_occured)):
            raise ScrSetupError(
                f"match chain {mc.chain_id} is unused, it has neither document nor content matching"
            )


def load_selenium_cookies(ctx: ScrContext) -> dict[str, dict[str, dict[str, Any]]]:
    assert ctx.selenium_driver is not None
    # the selenium function isn't type annotated properly
    cookies: list[dict[str, Any]
                  ] = ctx.selenium_driver.get_cookies()  # type: ignore
    cookie_dict: dict[str, dict[str, dict[str, Any]]] = {}
    for ck in cookies:
        if cast(str, ck["domain"]) not in cookie_dict:
            cookie_dict[ck["domain"]] = {}
        cookie_dict[ck["domain"]][ck["name"]] = ck
    return cookie_dict


def load_cookie_jar(ctx: ScrContext) -> None:
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
        raise ScrSetupError(f"failed to read cookie file: {str(ex)}")
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


def get_random_user_agent() -> UserAgent:
    # since this initialization is very slow, we cache it
    # this is mainly useful for the repl where the uar value can change
    if not hasattr(get_random_user_agent, "instance"):
        get_random_user_agent.__dict__["instance"] = UserAgent()
    return cast(
        UserAgent,
        get_random_user_agent.__dict__["instance"]
    ).get_random_user_agent()


def setup(ctx: ScrContext, special_args_occured: bool = False) -> None:
    global DEFAULT_CPF
    ctx.apply_defaults(ScrContext())

    if ctx.tor_browser_dir:
        if not ctx.selenium_variant.enabled():
            ctx.selenium_variant = SeleniumVariant.TORBROWSER
    load_cookie_jar(ctx)

    if ctx.user_agent is not None and ctx.user_agent_random:
        raise ScrSetupError(f"the options ua and uar are incompatible")
    elif ctx.user_agent_random:
        ctx.user_agent = get_random_user_agent()
    elif ctx.user_agent is None and not ctx.selenium_variant.enabled():
        ctx.user_agent = SCR_USER_AGENT

    # if no chains are specified, use the origin chain as chain 0
    if not ctx.match_chains:
        ctx.match_chains = [ctx.origin_mc]
        ctx.origin_mc.chain_id = 0

    for d in ctx.docs:
        if d.expand_match_chains_above is not None:
            d.match_chains.extend(
                ctx.match_chains[d.expand_match_chains_above:])

    for mc in ctx.match_chains:
        setup_match_chain(mc, ctx, special_args_occured)

    if len(ctx.docs) == 0:
        report = True
        if ctx.repl or special_args_occured:
            if not any(mc.has_content_matching or mc.has_document_matching for mc in ctx.match_chains):
                report = False
        if report:
            raise ScrSetupError("must specify at least one url or (r)file")

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
                prefix="Scr_downloads_"
            )

    if not ctx.selenium_variant.enabled():
        for mc in ctx.match_chains:
            mc.selenium_strategy = SeleniumStrategy.DISABLED
    elif ctx.selenium_driver is None:
        setup_selenium(ctx)

    if ctx.dl_manager is None and ctx.max_download_threads != 0:
        ctx.dl_manager = DownloadManager(
            ctx, ctx.max_download_threads, sys.stdout.isatty()
        )
    if ctx.dl_manager is not None:
        ctx.dl_manager.pom.reset()


def parse_prompt_option(
    val: str, options: list[tuple[T, OptionIndicatingStrings]],
    default: Optional[T] = None
) -> Optional[T]:
    val = val.strip().lower()
    if val == "":
        return default
    for opt, ois in options:
        if val in ois.matching:
            return opt
    return None


def parse_bool_string(val: str, default: Optional[bool] = None) -> Optional[bool]:
    return parse_prompt_option(val, [(True, YES_INDICATING_STRINGS), (False, NO_INDICATING_STRINGS)], default)


def prompt(prompt_text: str, options: list[tuple[T, OptionIndicatingStrings]], default: Optional[T] = None) -> T:
    assert len(options) > 1
    while True:
        res = parse_prompt_option(input(prompt_text), options, default)
        if res is None:
            option_names = [ois.representative for _opt, ois in options]
            print("please answer with " +
                  ", ".join(option_names[:-1]) + " or " + option_names[-1])
            continue
        return res


def prompt_yes_no(prompt_text: str, default: Optional[bool] = None) -> Optional[bool]:
    return prompt(prompt_text, [(True, YES_INDICATING_STRINGS), (False, NO_INDICATING_STRINGS)], default)


def selenium_get_url(ctx: ScrContext) -> Optional[str]:
    assert ctx.selenium_driver is not None
    try:
        return cast(str, ctx.selenium_driver.current_url)
    except (SeleniumWebDriverException, SeleniumMaxRetryError) as e:
        report_selenium_died(ctx)
        return None


def selenium_has_died(ctx: ScrContext) -> bool:
    assert ctx.selenium_driver is not None
    try:
        # throws an exception if the session died
        return not len(ctx.selenium_driver.window_handles) > 0
    except (SeleniumWebDriverException, SeleniumMaxRetryError) as e:
        return True


def gen_dl_temp_name(
    ctx: ScrContext, final_filepath: Optional[str]
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


def fetch_file(ctx: ScrContext, path: str, stream: bool = False) -> Union[bytes, BinaryIO]:
    try:
        f = open(path, "rb")
        if stream:
            return f
        try:
            return f.read()
        finally:
            f.close()
    except FileNotFoundError as ex:
        raise ScrFetchError("no such file or directory") from ex
    except IOError as ex:
        raise ScrFetchError(truncate(str(ex))) from ex


def try_read_data_url(cm: ContentMatch) -> Optional[bytes]:
    assert cm.url_parsed is not None
    if cm.url_parsed.scheme == "data":
        res = urllib.request.urlopen(
            cm.clm.result,
            timeout=cm.mc.ctx.request_timeout_seconds
        )
        try:
            data = res.read()
        finally:
            res.close()
        return cast(bytes, data)
    return None


def request_exception_to_scr_fetch_error(ex: requests.exceptions.RequestException) -> ScrFetchError:
    if isinstance(ex, requests.exceptions.InvalidURL):
        return ScrFetchError("invalid url")
    if isinstance(ex, requests.exceptions.ConnectionError):
        return ScrFetchError("connection failed")
    if isinstance(ex, requests.exceptions.ConnectTimeout):
        return ScrFetchError("connection timeout")
    return ScrFetchError(truncate(str(ex)))


def request_raw(
    ctx: ScrContext, path: str, path_parsed: urllib.parse.ParseResult,
    cookie_dict: Optional[dict[str, dict[str, dict[str, Any]]]] = None,
    proxies: Optional[dict[str, Optional[str]]] = None, stream: bool = False
) -> requests.Response:
    hostname = path_parsed.hostname if path_parsed.hostname else ""
    if cookie_dict is None:
        cookie_dict = ctx.cookie_dict
    cookies = {
        name: ck["value"]
        for name, ck in cookie_dict.get(hostname, {}).items()
    }
    headers = {'User-Agent': ctx.user_agent}

    res = requests.get(
        path, cookies=cookies, headers=headers, allow_redirects=True,
        proxies=proxies, timeout=ctx.request_timeout_seconds, stream=stream
    )
    return res


def sanitize_filename(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    # we do minimal sanitization here, but we intentionally allow slightly weird things
    # like files starting with dot because a user might actually want to do that
    filename = os.path.basename(filename)
    if filename.strip() == "":
        return None
    if filename in [".", ".."]:
        return None
    return filename


def try_get_filename_from_content_disposition(content_dispositon: Optional[str]) -> Optional[str]:
    if not content_dispositon:
        return None
    try:
        return sanitize_filename(pyrfc6266.parse_filename(content_dispositon))
    except pyparsing.exceptions.ParseException as ex:
        return None


def request_try_get_filename(res: requests.Response) -> Optional[str]:
    return try_get_filename_from_content_disposition(
        res.headers.get('Content-Disposition')
    )


def request_try_get_filesize(res: requests.Response) -> Optional[int]:
    cl = res.headers.get('Content-Length', None)
    if cl is None:
        return None
    try:
        return int(cl)
    except ValueError:
        return None


def requests_dl(
    ctx: ScrContext, path: str,
    path_parsed: urllib.parse.ParseResult,


) -> tuple[Union[MinimalInputStream, bytes, None], Optional[str]]:
    try:
        req = request_raw(ctx, path, path_parsed)
        data = req.content
        encoding = req.encoding
        req.close()
        return data, encoding
    except requests.exceptions.RequestException as ex:
        raise request_exception_to_scr_fetch_error(ex)


def report_selenium_died(ctx: ScrContext, is_err: bool = True) -> None:
    log(ctx, Verbosity.ERROR if is_err else Verbosity.WARN,
        "the selenium instance was closed unexpectedly")


def report_selenium_error(ctx: ScrContext, ex: Exception) -> None:
    log(ctx, Verbosity.ERROR, f"critical selenium error: {str(ex)}")


def advance_output_formatters(output_formatters: list[OutputFormatter], buf: Optional[bytes]) -> None:
    i = 0
    while i < len(output_formatters):
        if output_formatters[i].advance(buf):
            i += 1
        else:
            del output_formatters[i]


def selenium_get_full_page_source(ctx: ScrContext) -> tuple[str, lxml.html.HtmlElement]:
    drv = cast(SeleniumWebDriver, ctx.selenium_driver)
    text = drv.page_source
    doc_xml: lxml.html.HtmlElement = lxml.html.fromstring(text)
    iframes_xml_all_sources: list[lxml.html.HtmlElement] = doc_xml.xpath(
        "//iframe"
    )
    if not iframes_xml_all_sources:
        return text, doc_xml
    depth = 0
    try:
        iframe_stack: list[tuple[
            SeleniumWebElement, int, lxml.html.HtmlElement
        ]] = []
        while True:
            iframes_by_source: dict[str, lxml.html.HtmlElement] = {}
            for iframe in reversed(iframes_xml_all_sources):
                iframe_src = iframe.attrib["src"]
                iframe_src_escaped = xml.sax.saxutils.escape(iframe_src)
                if iframe_src_escaped in iframes_by_source:
                    iframes_by_source[iframe_src_escaped].append(iframe)
                else:
                    iframes_by_source[iframe_src_escaped] = [iframe]
            for iframe_src_escaped, iframes_xml in iframes_by_source.items():
                iframes_sel = drv.find_elements(
                    by=selenium.webdriver.common.by.By.XPATH,
                    value=f"//iframe[@src='{iframe_src_escaped}']"
                )
                len_sel = len(iframes_sel)
                len_xml = len(iframes_xml)
                if len_sel != len_xml:
                    log(
                        ctx, Verbosity.WARN,
                        f"iframe count diverged for iframe source in '{iframe_src_escaped}'"
                    )
                for i in range(0, min(len_sel, len_xml)):
                    iframe_stack.append(
                        (iframes_sel[i], depth + 1, iframes_xml[i])
                    )
            if not iframe_stack:
                break
            iframe_sel, depth_new, curr_xml = iframe_stack.pop()
            while depth_new <= depth:
                depth -= 1
                drv.switch_to.parent_frame()
            drv.switch_to.frame(iframe_sel)
            log(ctx, Verbosity.DEBUG,
                f"expanding iframe {curr_xml.attrib['src']}")
            depth = depth_new
            iframe_xml = lxml.html.fromstring(drv.page_source)
            curr_xml.append(iframe_xml)
            curr_xml = iframe_xml
            lxml.etree.XPath
            iframes_xml_all_sources = iframe_xml.xpath(".//iframe")

        return lxml.html.tostring(doc_xml), doc_xml
    finally:
        drv.switch_to.default_content()


def fetch_doc(ctx: ScrContext, doc: Document) -> None:
    if ctx.selenium_variant.enabled():
        if doc is not ctx.reused_doc or ctx.changed_selenium:
            log(
                ctx, Verbosity.INFO,
                f"getting selenium page source for {document_type_display_dict[doc.document_type]} '{doc.path}'"
            )
            selpath = doc.path
            if doc.document_type in [DocumentType.FILE, DocumentType.RFILE]:
                selpath = "file:" + os.path.realpath(selpath)
            try:
                cast(SeleniumWebDriver, ctx.selenium_driver).get(selpath)
            except SeleniumTimeoutException:
                ScrFetchError("selenium timeout")
        log(
            ctx, Verbosity.INFO,
            f"reloading selenium page source for {document_type_display_dict[doc.document_type]} '{doc.path}'"
        )
        decide_document_encoding(ctx, doc)
        doc.text, doc.xml = selenium_get_full_page_source(ctx)
        return
    if doc is ctx.reused_doc:
        log(
            ctx, Verbosity.INFO,
            f"reusing page content for {document_type_display_dict[doc.document_type]} '{doc.path}'"
        )
        ctx.reused_doc = None
        if doc.text and not ctx.changed_selenium:
            return
    if doc.document_type in [DocumentType.FILE, DocumentType.RFILE]:
        log(
            ctx, Verbosity.INFO,
            f"reading {document_type_display_dict[doc.document_type]} '{doc.path}'"
        )
        data = cast(bytes, fetch_file(ctx, doc.path, stream=False))
        encoding = decide_document_encoding(ctx, doc)
        doc.text = data.decode(encoding, errors="surrogateescape")
        return
    assert doc.document_type == DocumentType.URL

    log(
        ctx, Verbosity.INFO,
        f"downloading {document_type_display_dict[doc.document_type]} '{doc.path}'"
    )
    data, encoding = cast(tuple[bytes, str], requests_dl(
        ctx, doc.path, doc.path_parsed
    ))
    if data is None:
        raise ScrFetchError("empty response")
    doc.encoding = encoding
    encoding = decide_document_encoding(ctx, doc)
    doc.text = data.decode(encoding, errors="surrogateescape")
    return


def gen_final_content_format(format_str: str, cm: ContentMatch, filename: Optional[str] = None) -> bytes:
    with BytesIO(b"") as buf:
        of = OutputFormatter(format_str, cm, buf, None, filename)
        while of.advance():
            pass
        buf.seek(0)
        res = buf.read()
    return res


def normalize_link(
    ctx: ScrContext, mc: Optional[MatchChain], src_doc: Document,
    doc_path: Optional[str], link: str, link_parsed: urllib.parse.ParseResult
) -> tuple[str, urllib.parse.ParseResult]:
    doc_url_parsed = urllib.parse.urlparse(doc_path) if doc_path else None
    if src_doc.document_type == DocumentType.FILE:
        if not link_parsed.scheme:
            if not os.path.isabs(link):
                if doc_url_parsed is not None:
                    base = doc_url_parsed.path
                    if ctx.selenium_variant.enabled():
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


def get_ci_di_context(cm: ContentMatch) -> str:
    if cm.mc.has_document_matching:
        if cm.mc.content.multimatch:
            di_ci_context = f" (di={cm.di}, ci={cm.ci})"
        else:
            di_ci_context = f" (di={cm.di})"
    elif cm.mc.content.multimatch:
        di_ci_context = f" (ci={cm.ci})"
    else:
        di_ci_context = f""
    return di_ci_context


def handle_content_match(cm: ContentMatch) -> InteractiveResult:
    cm.di = cm.mc.di
    cm.ci = cm.mc.ci
    cm.mc.ci += 1
    cm.mc.content.apply_format_for_content_match(cm, cm.clm)

    if cm.llm is None:
        if cm.mc.need_label:
            cm.llm = LocatorMatch()
            cm.llm.fres = cast(str, cm.mc.label_default_format).format(
                **content_match_build_format_args(cm)
            )
            cm.llm.result = cm.llm.fres
    else:
        cm.mc.label.apply_format_for_content_match(cm, cm.llm)

    di_ci_context = get_ci_di_context(cm)

    if cm.llm is not None:
        label_context = f' (label "{cm.llm.result}")'
    else:
        label_context = ""

    while True:
        if not cm.mc.content_raw:
            cm.url_parsed = urllib.parse.urlparse(cm.clm.result)
            if not cm.mc.ctx.selenium_variant.enabled():
                doc_url = cm.doc.path
            else:
                sel_url = selenium_get_url(cm.mc.ctx)
                if sel_url is None:
                    return InteractiveResult.ERROR
                doc_url = sel_url

            cm.clm.result, cm.url_parsed = normalize_link(
                cm.mc.ctx, cm.mc, cm.doc, doc_url, cm.clm.result, cm.url_parsed
            )
        content_type = "content match" if cm.mc.content_raw else "content link"
        if cm.mc.content.interactive:
            prompt_options = [
                (InteractiveResult.ACCEPT, YES_INDICATING_STRINGS),
                (InteractiveResult.REJECT, NO_INDICATING_STRINGS),
                (InteractiveResult.EDIT, EDIT_INDICATING_STRINGS),
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
                prompt_msg = f'"{cm.doc.path}"{di_ci_context}{label_context}: accept {content_type} "{cm.clm.result}"'

            res = prompt(
                f'{prompt_msg} [Yes/no/edit{inspect_opt_str}/chainskip/docskip]? ',
                prompt_options,
                InteractiveResult.ACCEPT
            )
            if res is InteractiveResult.ACCEPT:
                break
            if res == InteractiveResult.INSPECT:
                print(
                    f'content for "{cm.doc.path}"{label_context}:\n' + cm.clm.result)
                continue
            if res is not InteractiveResult.EDIT:
                return res
            if not cm.mc.content_raw:
                cm.clm.result = input(f"enter new {content_type}:\n")
            else:
                print(
                    f'enter new {content_type} (terminate with a newline followed by the string "{cm.mc.content_escape_sequence}"):\n')
                cm.clm.result = ""
                while True:
                    cm.clm.result += input() + "\n"
                    i = cm.clm.result.find(
                        "\n" + cm.mc.content_escape_sequence)
                    if i != -1:
                        cm.clm.result = cm.clm.result[:i]
                        break
        break
    if cm.mc.label.interactive:
        assert cm.llm is not None
        while True:
            if not cm.mc.is_valid_label(cm.clm.result):
                log(cm.mc.ctx, Verbosity.WARN,
                    f'"{cm.doc.path}": labels cannot contain a slash ("{cm.llm.result}")')
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
                    prompt_msg = f'"{cm.doc.path}"{di_ci_context}: accept content label "{cm.llm.result}"'
                else:
                    inspect_opt_str = ""
                    prompt_msg = f'"{cm.doc.path}": {content_type} {cm.clm.result}{di_ci_context}: accept content label "{cm.llm.result}"'

                res = prompt(
                    f'{prompt_msg} [Yes/no/edit/{inspect_opt_str}/chainskip/docskip]? ',
                    prompt_options,
                    InteractiveResult.ACCEPT
                )
                if res == InteractiveResult.ACCEPT:
                    break
                if res == InteractiveResult.INSPECT:
                    print(
                        f'"{cm.doc.path}": {content_type} for "{cm.llm.result}":\n' + cm.clm.result)
                    continue
                if res != InteractiveResult.EDIT:
                    return res
            cm.llm.result = input("enter new label: ")

    job = DownloadJob(cm)
    if cm.mc.save_path_interactive:
        res = job.handle_save_path()
        if res != InteractiveResult.ACCEPT:
            return res
    if cm.mc.ctx.dl_manager is not None:
        if job.requires_download():
            cm.mc.ctx.dl_manager.submit(job)
        else:
            job.setup_print_stream(cm.mc.ctx.dl_manager.pom)
            job.run_job()
    else:
        job.run_job()

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
                (InteractiveResult.EDIT, EDIT_INDICATING_STRINGS),
                (InteractiveResult.SKIP_CHAIN, CHAIN_SKIP_INDICATING_STRINGS),
                (InteractiveResult.SKIP_DOC, DOC_SKIP_INDICATING_STRINGS)
            ],
            InteractiveResult.ACCEPT
        )
        if res == InteractiveResult.EDIT:
            doc.path = input("enter new document: ")
            continue
        return res


def gen_content_matches(
    mc: MatchChain, doc: Document, last_doc_path: str
) -> tuple[list[ContentMatch], int]:
    text = cast(str, doc.text)
    content_matches: list[ContentMatch] = []
    content_lms_xp: list[LocatorMatch] = mc.content.match_xpath(
        text, doc.xml, doc.path, mc.has_content_xpaths
    )
    label_lms: list[LocatorMatch] = []
    if mc.has_label_matching and not mc.labels_inside_content:
        label_lms = mc.label.match_xpath(text, doc.xml, doc.path, False)
        label_lms = mc.label.apply_regex_matches(label_lms)
        label_lms = mc.label.apply_js_matches(doc, mc, label_lms)
    match_index = 0
    labels_none_for_n = 0
    for clm_xp in content_lms_xp:
        if mc.labels_inside_content and mc.label.xpath:
            label_lms = mc.label.match_xpath(
                clm_xp.result, clm_xp.xmatch_xml, doc.path, False
            )
            # in case we have label xpath matching, the label regex matching
            # will be done on the LABEL xpath result, not the content one
            # even for lic = y
            label_lms = mc.label.apply_regex_matches(label_lms)
            label_lms = mc.label.apply_js_matches(doc, mc, label_lms)

        content_lms = mc.content.apply_regex_matches([clm_xp])
        content_lms = mc.content.apply_js_matches(doc, mc, content_lms)
        for clm in content_lms:
            llm: Optional[LocatorMatch] = None
            if mc.labels_inside_content:
                if not mc.label.xpath:
                    llm = LocatorMatch()
                    llm.result = clm.result
                    label_lms = mc.label.apply_regex_matches([llm], False)
                    label_lms = mc.label.apply_js_matches(
                        doc, mc, label_lms, False
                    )
                if len(label_lms) == 0:
                    if not mc.label_allow_missing:
                        labels_none_for_n += 1
                        continue
                else:
                    llm = label_lms[0]
            else:
                if not mc.label.multimatch and len(label_lms) > 0:
                    llm = label_lms[0]
                elif match_index < len(label_lms):
                    llm = label_lms[match_index]
                elif not mc.label_allow_missing:
                    labels_none_for_n += 1
                    continue
                else:
                    llm = None

            content_matches.append(ContentMatch(clm, llm, mc, doc))
        match_index += 1
    return content_matches, labels_none_for_n


def gen_document_matches(mc: MatchChain, doc: Document, last_doc_path: str) -> list[Document]:
    document_matches = []
    document_lms = mc.document.match_xpath(
        cast(str, doc.text), doc.xml, doc.path, False
    )
    document_lms = mc.document.apply_regex_matches(document_lms)
    document_lms = mc.document.apply_js_matches(doc, mc, document_lms)
    for dlm in document_lms:
        ndoc = Document(
            doc.document_type.derived_type(),
            "",
            mc,
            mc.document_output_chains,
            None,
            dlm
        )
        mc.document.apply_format_for_document_match(ndoc, mc, dlm)
        ndoc.path, ndoc.path_parsed = normalize_link(
            mc.ctx, mc, doc, last_doc_path, dlm.result,
            urllib.parse.urlparse(dlm.result)
        )
        document_matches.append(ndoc)

    return document_matches


def make_padding(ctx: ScrContext, count_number: int) -> tuple[str, str]:
    content_count_pad_len = (
        ctx.selenium_content_count_pad_length
        - min(len(str(count_number)), ctx.selenium_content_count_pad_length)
    )
    rpad = int(content_count_pad_len / 2)
    lpad = content_count_pad_len - rpad
    return lpad * " ", rpad * " "


def handle_interactive_chains(
    ctx: ScrContext,
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
            [
                (InteractiveResult.ACCEPT, YES_INDICATING_STRINGS),
                (
                    InteractiveResult.SKIP_DOC,
                    OptionIndicatingStrings(
                        "skip",
                        set_join(
                            SKIP_INDICATING_STRINGS.matching,
                            NO_INDICATING_STRINGS.matching
                        )
                    )
                )
            ],
            InteractiveResult.ACCEPT
        )
        if result is None:
            print('please answer with "yes" or "skip"')
            sys.stdout.write(msg)
            sys.stdout.flush()
    return result, msg


def match_chain_was_satisfied(mc: MatchChain) -> tuple[bool, bool]:
    satisfied = False
    interactive = False
    if not mc.ctx.selenium_variant.enabled() or mc.selenium_strategy is SeleniumStrategy.PLAIN:
        satisfied = True
    elif mc.selenium_strategy == SeleniumStrategy.ANYMATCH:
        if mc.need_content_matches():
            if mc.content_matches:
                satisfied = True
        if mc.need_document_matches(True):
            if mc.document_matches:
                satisfied = True
    else:
        assert mc.selenium_strategy in [
            SeleniumStrategy.INTERACTIVE, SeleniumStrategy.DEDUP
        ]
        interactive = True

    return satisfied, interactive


def handle_match_chain(mc: MatchChain, doc: Document, last_doc_path: str) -> None:
    if mc.need_content_matches():
        content_matches, mc.labels_none_for_n = gen_content_matches(
            mc, doc, last_doc_path
        )
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


def accept_for_match_chain(
    mc: MatchChain, doc: Document,
    content_skip_doc: bool, documents_skip_doc: bool,
    new_docs: list[Document]
) -> tuple[bool, bool]:
    if not mc.ci_continuous:
        mc.ci = mc.cimin
    if not content_skip_doc:
        for i, cm in enumerate(mc.content_matches):
            if not mc.has_label_matching or cm.llm is not None:
                if mc.ci > mc.cimax:
                    break
                res = handle_content_match(cm)
                if res == InteractiveResult.SKIP_CHAIN:
                    break
                if res == InteractiveResult.SKIP_DOC:
                    content_skip_doc = True
                    break
            else:
                rem = len(mc.content_matches) - i
                log(
                    mc.ctx,
                    Verbosity.WARN,
                    f"no labels: skipping {rem} remaining"
                    + f" content match{'es' if rem > 1 else ''} in {doc.path}"
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


def decide_document_encoding(ctx: ScrContext, doc: Document) -> str:
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


def parse_xml(ctx: ScrContext, doc: Document) -> None:
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


def process_document_queue(ctx: ScrContext) -> Optional[Document]:
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
            if not ctx.selenium_variant.enabled() or (doc is ctx.reused_doc and not ctx.changed_selenium):
                continue

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
        except ScrFetchError as ex:
            log(ctx, Verbosity.ERROR, f"Failed to fetch {doc.path}: {str(ex)}")
            continue
        static_content = (
            doc.document_type != DocumentType.URL
            or not ctx.selenium_variant.enabled()
        )
        last_msg = ""
        content_change = True
        while unsatisfied_chains > 0:
            try_number += 1
            same_content = static_content and not content_change
            if try_number > 1 and not same_content:
                assert(ctx.selenium_variant.enabled())
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
                        log(ctx, Verbosity.WARN,
                            f"selenium failed to fetch page source: {str(ex)}")
                    same_content = True

            if not same_content or content_change:
                content_change = False
                interactive_chains = []
                if have_xpath_matching and doc.xml is None:
                    parse_xml(ctx, doc)
                    if doc.xml is None:
                        break
                for mc in doc.match_chains:
                    if mc.satisfied:
                        continue
                    mc.js_executed = False
                    handle_match_chain(mc, doc, last_doc_path)
                    satisfied, interactive = match_chain_was_satisfied(mc)
                    if satisfied:
                        log(
                            ctx, Verbosity.DEBUG,
                            f"chain {mc.chain_id} satisfied for  {doc.path}"
                        )
                        mc.satisfied = True
                        unsatisfied_chains -= 1
                        if mc.has_xpath_matching:
                            have_xpath_matching -= 1
                    elif interactive:
                        interactive_chains.append(mc)
                    if mc.js_executed:
                        content_change = True
                        break
                if content_change:
                    continue

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


def finalize(ctx: ScrContext) -> None:
    if ctx.dl_manager:
        try:
            ctx.dl_manager.pom.main_thread_done()
            success = True
        finally:
            if not success:
                ctx.abort = True
            ctx.dl_manager.terminate(ctx.abort)
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
    success = True


def begins(string: str, begin: str) -> bool:
    return len(string) >= len(begin) and string[0:len(begin)] == begin


def parse_mc_range_int(ctx: ScrContext, v: str, arg: str) -> int:
    try:
        return int(v)
    except ValueError as ex:
        raise ScrSetupError(
            f"failed to parse '{v}' as an integer for match chain specification of '{arg}'"
        )


def extend_match_chain_list(ctx: ScrContext, needed_id: int) -> None:
    if len(ctx.match_chains) > needed_id:
        return
    for i in range(len(ctx.match_chains), needed_id+1):
        mc = copy.deepcopy(ctx.origin_mc)
        mc.chain_id = i
        ctx.match_chains.append(mc)


def parse_simple_mc_range(ctx: ScrContext, mc_spec: str, arg: str) -> Iterable[MatchChain]:
    sections = mc_spec.split(",")
    ranges = []
    for s in sections:
        s = s.strip()
        if s == "":
            raise ScrSetupError(
                "invalid empty range in match chain specification of '{arg}'")
        dash_split = [r.strip() for r in s.split("-")]
        if len(dash_split) > 2 or s == "-":
            raise ScrSetupError(
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
                    raise ScrSetupError(
                        f"second value must be larger than first for range {s} "
                        + f"in match chain specification of '{arg}'"
                    )
                extend_match_chain_list(ctx, snd)
            ranges.append(ctx.match_chains[fst: snd + 1])
    return itertools.chain(*ranges)


def parse_mc_range(ctx: ScrContext, mc_spec: str, arg: str) -> Iterable[MatchChain]:
    if mc_spec == "":
        return [ctx.defaults_mc]

    esc_split = [x.strip() for x in mc_spec.split("^")]
    if len(esc_split) > 2:
        raise ScrSetupError(
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
    ctx: ScrContext, argname: str, arg: str,
    support_blank: bool = False, blank_value: str = ""
) -> Optional[tuple[Iterable[MatchChain], str]]:
    if not begins(arg, argname):
        return None
    argname_len = len(argname)
    eq_pos = arg.find("=")
    if eq_pos == -1:
        mc_spec = arg[argname_len:]
        if arg != argname:
            if not MATCH_CHAIN_ARGUMENT_REGEX.match(mc_spec):
                return None
        elif not support_blank:
            raise ScrSetupError("missing equals sign in argument '{arg}'")
        pre_eq_arg = arg
        value = blank_value
    else:
        mc_spec = arg[argname_len: eq_pos]
        if not MATCH_CHAIN_ARGUMENT_REGEX.match(mc_spec):
            return None
        pre_eq_arg = arg[:eq_pos]
        value = arg[eq_pos+1:]
    return parse_mc_range(ctx, mc_spec, pre_eq_arg), value


def parse_mc_arg_as_range(ctx: ScrContext, argname: str, argval: str) -> list[MatchChain]:
    return list(parse_mc_range(ctx, argval, argname))


def apply_mc_arg(
    ctx: ScrContext, argname: str, config_opt_names: list[str], arg: str,
    value_parse: Callable[[str, str], Any] = lambda x, _arg: x,
    support_blank: bool = False, blank_value: str = ""
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
            raise ScrSetupError(
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

    if v in YES_INDICATING_STRINGS.matching:
        return True
    if v in NO_INDICATING_STRINGS.matching:
        return False
    raise ScrSetupError(f"cannot parse '{v}' as a boolean in '{arg}'")


def parse_int_arg(v: str, arg: str) -> int:
    try:
        return int(v)
    except ValueError:
        raise ScrSetupError(f"cannot parse '{v}' as an integer in '{arg}'")


def parse_non_negative_float_arg(v: str, arg: str) -> float:
    try:
        f = float(v)
    except ValueError:
        raise ScrSetupError(f"cannot parse '{v}' as an number in '{arg}'")
    if f < 0:
        raise ScrSetupError(f"negative number '{v}' not allowed for '{arg}'")
    return f


def parse_encoding_arg(v: str, arg: str) -> str:
    if not verify_encoding(v):
        raise ScrSetupError(f"unknown encoding in '{arg}'")
    return v


def select_variant(val: str, variants_dict: dict[str, T], default: Optional[T] = None) -> Optional[T]:
    val = val.strip().lower()
    if val == "":
        return default
    if val in variants_dict:
        return variants_dict[val]
    match = None
    for k, v in variants_dict.items():
        if begins(k, val):
            if match is not None:
                return None  # we have two conflicting matches
            match = v
    return match


def parse_variant_arg(val: str, variants_dict: dict[str, T], arg: str, default: Optional[T] = None) -> T:
    res = select_variant(val, variants_dict, default)
    if res is None:
        raise ScrSetupError(
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
    ctx: ScrContext, argname: str, doctype: DocumentType, arg: str
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
    ctx: ScrContext, optname: str, argname: str, arg: str,
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
            raise ScrSetupError(
                f"missing '=' and value for option '{optname}'"
            )
    else:
        nc = arg[len(optname):]
        if MATCH_CHAIN_ARGUMENT_REGEX.match(nc):
            raise ScrSetupError(
                "option '{optname}' does not support match chain specification"
            )
        if nc[0] != "=":
            return False
        val = get_arg_val(arg)
    if ctx.__dict__[argname] is not None:
        raise ScrSetupError(f"error: {argname} specified twice")
    ctx.__dict__[argname] = value_parse(val, arg)
    return True


def resolve_repl_defaults(
    ctx_new: ScrContext, ctx: ScrContext, last_doc: Optional[Document]
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
        except (SeleniumWebDriverException, SeleniumMaxRetryError) as ex:
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


def run_repl(initial_ctx: ScrContext) -> int:
    try:
        # run with initial args
        readline.set_auto_history(False)
        readline.add_history(shlex.join(sys.argv[1:]))
        tty = sys.stdin.isatty()
        stable_ctx = initial_ctx
        ctx: Optional[ScrContext] = initial_ctx
        success = False
        while True:
            try:
                if ctx is not None:
                    try:
                        last_doc = process_document_queue(ctx)
                    except ScrMatchError as ex:
                        log(ctx, Verbosity.ERROR, str(ex))
                    if ctx.dl_manager:
                        ctx.dl_manager.pom.main_thread_done()
                        ctx.dl_manager.wait_until_jobs_done()
                    if ctx.exit:
                        return ctx.error_code
                    stable_ctx = ctx
                    ctx = None
                try:
                    line = input(f"{SCRIPT_NAME}> " if tty else "")
                    readline.add_history(line)
                except EOFError:
                    if tty:
                        print("")
                    success = True
                    return 0
                try:
                    args = shlex.split(line)
                except ValueError as ex:
                    log(stable_ctx, Verbosity.ERROR,
                        "malformed arguments: " + str(ex))
                    continue
                if not len(args):
                    continue

                ctx_new = ScrContext(blank=True)
                try:
                    special_args_occured = parse_args(ctx_new, args)
                except ScrSetupError as ex:
                    log(stable_ctx, Verbosity.ERROR, str(ex))
                    continue

                resolve_repl_defaults(ctx_new, stable_ctx, last_doc)
                ctx = ctx_new

                try:
                    setup(ctx, special_args_occured=special_args_occured)
                except ScrSetupError as ex:
                    log(ctx, Verbosity.ERROR, str(ex))
                    if ctx.exit:
                        stable_ctx = ctx
                        return ctx.error_code
                    ctx = None
            except KeyboardInterrupt:
                print("")
                continue
    finally:
        if not success:
            stable_ctx.abort = True
        finalize(stable_ctx)


def match_traditional_cli_arg(arg: str, true_opt_name: str, aliases: set[str]) -> Optional[bool]:
    tolen = len(true_opt_name)
    arglen = len(arg)
    if begins(arg, f"{true_opt_name}"):
        if arglen > tolen:
            if arg[tolen] != "=":
                return None
        return parse_bool_arg(arg[len("{true_opt_name}="):], arg)
    if arg in aliases:
        return True
    return None


def parse_args(ctx: ScrContext, args: Iterable[str]) -> bool:
    special_args_occured = False
    for arg in args:
        if match_traditional_cli_arg(arg, "help", {"-h", "--help"}):
            help()
            special_args_occured = True
            continue
        if match_traditional_cli_arg(arg, "version", {"-v", "--version"}):
            print(f"scr {VERSION}")
            special_args_occured = True
            continue
        if match_traditional_cli_arg(arg, "install-geckodriver", {"--install-geckodriver"}):
            special_args_occured = True
            try:
                sd = get_script_dir()
                target = os.path.join(sd, "geckodriver")
                if os.path.exists(target):
                    log(
                        ctx, Verbosity.INFO,
                        f"a file is already present in {target}"
                    )
                    continue
                path = geckodriver_autoinstaller.install(cwd=True)
                os.symlink(path, target)
                log(ctx, Verbosity.INFO, f"installed geckodriver at {path}")
            except (RuntimeError, urllib.error.URLError, FileNotFoundError) as ex:
                raise ScrSetupError(
                    f"failed to install geckodriver: '{str(ex)}'"
                )
            continue

         # content args
        if apply_mc_arg(ctx, "cx", ["content", "xpath"], arg):
            continue
        if apply_mc_arg(ctx, "cr", ["content", "regex"], arg):
            continue
        if apply_mc_arg(ctx, "cf", ["content", "format"], arg):
            continue
        if apply_mc_arg(ctx, "cjs", ["content", "js_script"], arg):
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
        if apply_mc_arg(ctx, "ljs", ["label", "js_script"], arg):
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
        if apply_mc_arg(ctx, "ldf", ["label_default_format"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "fdf", ["filename_default_format"], arg, parse_bool_arg, True):
            continue

        # document args
        if apply_mc_arg(ctx, "dx", ["document", "xpath"], arg):
            continue
        if apply_mc_arg(ctx, "dr", ["document", "regex"], arg):
            continue
        if apply_mc_arg(ctx, "df", ["document", "format"], arg):
            continue
        if apply_mc_arg(ctx, "djs", ["document", "js_script"], arg):
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

        if apply_ctx_arg(
            ctx, "sel", "selenium_variant", arg,
            lambda v, arg: parse_variant_arg(
                v, selenium_variants_dict, arg, SeleniumVariant.FIREFOX
            ),
            True
        ):
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

        raise ScrSetupError(f"unrecognized option: '{arg}'")
    return special_args_occured


def run_scr() -> int:
    ctx = ScrContext(blank=True)
    if len(sys.argv) < 2:
        log_raw(
            Verbosity.ERROR,
            f"missing command line options. Consider {SCRIPT_NAME} --help"
        )
        return 1

    try:
        special_args_occured = parse_args(ctx, sys.argv[1:])
        setup(ctx, special_args_occured)
    except ScrSetupError as ex:
        log_raw(Verbosity.ERROR, str(ex))
        return 1
    if ctx.repl:
        ec = run_repl(ctx)
    else:
        success = False
        try:
            process_document_queue(ctx)
            success = True
        except ScrMatchError as ex:
            log(ctx, Verbosity.ERROR, str(ex))
        finally:
            if not success:
                ctx.abort = True
            finalize(ctx)
        ec = ctx.error_code
    return ec


def main() -> None:
    try:
        # to silence: "Setting a profile has been deprecated" on launching tor
        warnings.filterwarnings(
            "ignore", module=".*selenium.*", category=DeprecationWarning
        )
        exit(run_scr())
    except BrokenPipeError:
        abort_on_broken_pipe()
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
