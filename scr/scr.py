#!/usr/bin/env python3
import functools
import subprocess
import selenium.webdriver
from abc import ABC, abstractmethod
import multiprocessing
from typing import Any, Optional, BinaryIO, TextIO, Union, cast
import mimetypes
import shutil
from io import BytesIO
import shlex
import lxml
import lxml.etree
import lxml.html
import pyrfc6266
import requests
import sys
import xml.sax.saxutils
import select
import re
import os
from string import Formatter
import readline
import urllib.parse
from random_user_agent.user_agent import UserAgent
import pyparsing.exceptions
from tbselenium.tbdriver import TorBrowserDriver
import selenium
import selenium.webdriver.common.by
from http.cookiejar import MozillaCookieJar
from selenium.webdriver.remote.webelement import WebElement as SeleniumWebElement
from selenium.webdriver.firefox.service import Service as SeleniumFirefoxService
from selenium.webdriver.chrome.service import Service as SeleniumChromeService
from selenium.webdriver.remote.webdriver import WebDriver as SeleniumWebDriver
from selenium.common.exceptions import WebDriverException as SeleniumWebDriverException
from selenium.common.exceptions import TimeoutException as SeleniumTimeoutException

# this is of course not really a selenium exception,
# but selenium throws it arbitrarily, just like SeleniumWebDriverException,
# and that is the only way in which we use it
from urllib3.exceptions import MaxRetryError as SeleniumMaxRetryError
import selenium.webdriver.firefox.webdriver
from collections import deque
import time
import tempfile
import warnings
import urllib.request

from .input_sequences import *
from .definitions import *
from .download_job import DownloadManager, PrintOutputStream, DownloadJob, MinimalInputStream
from .locator import LocatorMatch
from .selenium_driver_download import get_preferred_selenium_driver_path, try_get_local_selenium_driver_path
from .content_match import ContentMatch
from .match_chain import MatchChain
from .scr_context import ScrContext
from . import document, utils, config_data_class, args_parsing, utils


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
        filename: Optional[str]
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

    # returns True if it has not reached the end yet
    def advance(self, expected_buffer_size: int = 0, buffer: Optional[bytes] = None) -> bool:
        while True:
            if self._found_stream:
                if buffer is None:
                    return True
                if buffer:  # avoid length zero buffers which may cause errors
                    self._out_stream.write(buffer)
                if len(buffer) == expected_buffer_size:
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


def dict_update_unless_none(current: dict[K, Any], updates: dict[K, Any]) -> None:
    current.update({
        k: v for k, v in updates.items() if v is not None
    })


def apply_general_format_args(doc: document.Document, mc: MatchChain, args_dict: dict[str, Any], ci: Optional[int]) -> None:
    dict_update_unless_none(args_dict, {
        "cenc": doc.encoding,
        "cesc": mc.content_escape_sequence,
        "dl":   doc.path,
        "chain": mc.chain_id,
        "di": mc.di,
        "ci": ci
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
    content: Any = None,
    filename: Optional[str] = None
) -> dict[str, Any]:
    args_dict: dict[str, Any] = {}
    apply_general_format_args(cm.doc, cm.mc, args_dict, ci=cm.ci)
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


def selenium_build_firefox_options(
    ctx: ScrContext
) -> selenium.webdriver.FirefoxOptions:
    ff_options = selenium.webdriver.FirefoxOptions()
    if ctx.selenium_headless:
        ff_options.headless = True
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
    cwd = os.getcwd()
    driver_executable = get_preferred_selenium_driver_path(
        SeleniumVariant.TORBROWSER
    )
    if ctx.tor_browser_dir is None:
        tb_env_var = "TOR_BROWSER_DIR"
        if tb_env_var in os.environ:
            ctx.tor_browser_dir = os.environ[tb_env_var]
        else:
            raise ScrSetupError(f"no tbdir specified, check --help")
    try:
        ctx.selenium_driver = TorBrowserDriver(
            ctx.tor_browser_dir, tbb_logfile_path=ctx.selenium_log_path,
            executable_path=driver_executable,
            options=selenium_build_firefox_options(ctx)
        )

    except SeleniumWebDriverException as ex:
        raise ScrSetupError(f"failed to start tor browser: {str(ex)}")
    os.chdir(cwd)  # restore cwd that is changed by tor for some reason


def setup_selenium_firefox(ctx: ScrContext) -> None:
    driver_executable = get_preferred_selenium_driver_path(
        SeleniumVariant.FIREFOX
    )
    try:
        ctx.selenium_driver = selenium.webdriver.Firefox(
            options=selenium_build_firefox_options(ctx),
            service=SeleniumFirefoxService(  # type: ignore
                log_path=ctx.selenium_log_path,
                executable_path=driver_executable
            )
        )
    except SeleniumWebDriverException as ex:
        ex_msg = str(ex).strip('\n ')
        err_msg = f"failed to start geckodriver: {ex_msg}"

        if try_get_local_selenium_driver_path(SeleniumVariant.FIREFOX) is None:
            # this is slightly hacky, but i like the way it looks
            err_msg += f"\n{verbosities_display_dict[Verbosity.INFO]}consider running '{SCRIPT_NAME} selinstall=firefox'"
        raise ScrSetupError(err_msg)


def setup_selenium_chrome(ctx: ScrContext) -> None:
    driver_executable = get_preferred_selenium_driver_path(
        SeleniumVariant.CHROME
    )
    options = selenium.webdriver.ChromeOptions()
    if ctx.selenium_headless:
        options.headless = True
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
            service=SeleniumChromeService(  # type: ignore
                log_path=ctx.selenium_log_path,
                executable_path=driver_executable
            )
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
    conf: config_data_class.ConfigDataClass, attrib_path: list[str], dummy_cm: ContentMatch,
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
    mcc = len(mc.ctx.match_chains)
    if mcc > 1:
        form += f"{{chain:{len(str(mcc))}}}_"

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


def setup_match_chain(mc: MatchChain, ctx: ScrContext) -> None:

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
        if l.parses_documents():
            mc.parses_documents = True

    if any(l.xpath is not None for l in locators):
        mc.has_xpath_matching = True
    if mc.label.is_active():
        mc.has_label_matching = True
    if mc.labels_inside_content is not None and mc.label.xpath is not None:
        mc.has_content_xpaths = True
    if mc.document.is_active():
        mc.has_document_matching = True
        mc.parses_documents = True
    if mc.label.interactive or mc.content.interactive:
        mc.has_interactive_matching = True

    if mc.has_label_matching or mc.content.is_active():
        mc.has_content_matching = True
    elif mc.content_print_format or mc.content_save_format:
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
        if not (mc.chain_id == 0 and (mc.ctx.repl or mc.ctx.special_args_occured)):
            raise ScrSetupError(
                f"match chain {mc.chain_id} is unused, it has neither document nor content matching"
            )
    if not mc.content_raw:
        mc.parses_documents = True
    if not mc.parses_documents:
        # prepare chain to be used in the document -> content link optimization
        mc.content_raw = False


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


def setup(ctx: ScrContext) -> None:
    global DEFAULT_CPF

    if ctx.tor_browser_dir:
        if ctx.selenium_variant is None:
            ctx.selenium_variant = SeleniumVariant.TORBROWSER
    elif ctx.selenium_headless:
        if ctx.selenium_variant is None:
            ctx.selenium_variant = SeleniumVariant.default()
    ctx.apply_defaults(ScrContext())
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
        setup_match_chain(mc, ctx)

    if len(ctx.docs) == 0:
        report = True
        if ctx.repl or ctx.special_args_occured:
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
        raise ScrFetchError(utils.truncate(str(ex))) from ex


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
    return ScrFetchError(utils.truncate(str(ex)))


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


def fetch_doc(ctx: ScrContext, doc: document.Document) -> None:
    if ctx.selenium_variant.enabled():
        if doc is not ctx.reused_doc or ctx.changed_selenium:
            log(
                ctx, Verbosity.INFO,
                f"getting selenium page source for {document_type_display_dict[doc.document_type]} '{doc.path}'"
            )
            selpath = doc.path
            if doc.document_type in [document.DocumentType.FILE, DocumentType.RFILE]:
                selpath = "file:" + os.path.realpath(selpath)
            try:
                cast(SeleniumWebDriver, ctx.selenium_driver).get(selpath)
            except SeleniumTimeoutException:
                ScrFetchError("selenium timeout")
        log(
            ctx, Verbosity.INFO,
            f"reloading selenium page source for {document_type_display_dict[doc.document_type]} '{doc.path}'"
        )
        doc.decide_encoding(ctx)
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
    if doc.document_type in [document.DocumentType.FILE, DocumentType.RFILE]:
        log(
            ctx, Verbosity.INFO,
            f"reading {document_type_display_dict[doc.document_type]} '{doc.path}'"
        )
        data = cast(bytes, fetch_file(ctx, doc.path, stream=False))
        encoding = doc.decide_encoding(ctx)
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
    encoding = doc.decide_encoding(ctx)
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
    cm.mc.content.apply_format_for_content_match(cm, cm.clm)
    cm.mc.ci += 1

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


def handle_document_match(mc: MatchChain, doc: document.Document) -> InteractiveResult:
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
    mc: MatchChain, doc: document.Document, last_doc_path: str, doc_as_content: bool
) -> tuple[list[ContentMatch], int]:
    if doc_as_content:
        dummy_llm = None
        if mc.has_label_matching:
            dummy_llm = LocatorMatch()
        dummy_clm = LocatorMatch()
        dummy_clm.result = doc.path
        dummy_doc = doc
        if doc.document_type.derived_type() == DocumentType.FILE:
            # - we need normalize url to not change relative pathes
            # - we also need the derived type FILE even for rfiles
            # - we can't just change the document_type because this messes
            #   with last_doc for the repl
            dummy_doc = document.Document(
                DocumentType.CONTENT_FILE, path=doc.path, src_mc=doc.src_mc,
                locator_match=doc.locator_match, path_parsed=doc.path_parsed
            )
        return [ContentMatch(dummy_clm, dummy_llm, mc, dummy_doc)], 0
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


def gen_document_matches(mc: MatchChain, doc: document.Document, last_doc_path: str) -> list[document.Document]:

    document_matches = []
    document_lms = mc.document.match_xpath(
        cast(str, doc.text), doc.xml, doc.path, False
    )
    document_lms = mc.document.apply_regex_matches(document_lms)
    document_lms = mc.document.apply_js_matches(doc, mc, document_lms)
    for dlm in document_lms:
        ndoc = document.Document(
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
    doc: document.Document,
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
            [sys.stdin], [], [], ctx.selenium_poll_frequency_secs
        )
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


def handle_match_chain(mc: MatchChain, doc: document.Document, last_doc_path: str, doc_as_content: bool) -> None:
    if mc.need_content_matches():
        content_matches, mc.labels_none_for_n = gen_content_matches(
            mc, doc, last_doc_path, doc_as_content
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
    mc: MatchChain, doc: document.Document,
    content_skip_doc: bool, documents_skip_doc: bool,
    new_docs: list[document.Document]
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


def normalize_link(
    ctx: ScrContext, mc: Optional[MatchChain],
    src_doc: 'document.Document',
    doc_path: Optional[str], link: str, link_parsed: urllib.parse.ParseResult
) -> tuple[str, urllib.parse.ParseResult]:
    if src_doc.document_type == document.DocumentType.CONTENT_FILE:
        return link, link_parsed
    doc_url_parsed = urllib.parse.urlparse(doc_path) if doc_path else None
    if src_doc.document_type == document.DocumentType.FILE:
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
    if doc_url_parsed and link_parsed.netloc == "" and src_doc.document_type == document.DocumentType.URL:
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


def parse_xml(ctx: ScrContext, doc: document.Document) -> None:
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


def process_document_queue(ctx: ScrContext) -> Optional[document.Document]:
    doc = None
    while ctx.docs:
        doc = ctx.docs.popleft()
        last_doc_path = doc.path
        unsatisfied_chains = 0
        have_xpath_matching = 0
        doc_as_content_opt_possible = not ctx.selenium_variant.enabled()
        for mc in doc.match_chains:
            if mc.need_document_matches(False) or mc.need_content_matches():
                if mc.parses_documents:
                    doc_as_content_opt_possible = False
                unsatisfied_chains += 1
                mc.satisfied = False
                if mc.has_xpath_matching:
                    have_xpath_matching += 1
        if unsatisfied_chains == 0:
            if not ctx.selenium_variant.enabled() or (doc is ctx.reused_doc and not ctx.changed_selenium):
                continue

        try_number = 0
        try:
            if not doc_as_content_opt_possible:
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
                        break
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
                    handle_match_chain(mc, doc, last_doc_path,
                                       doc_as_content_opt_possible)
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
        new_docs: list[document.Document] = []
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
        success = False
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


def resolve_repl_defaults(
    ctx_new: ScrContext, ctx: ScrContext, last_doc: Optional[document.Document]
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
            if utils.begins(doc_url, "file:"):
                path = doc_url[len("file:"):]
                if not last_doc or os.path.realpath(last_doc.path) != os.path.realpath(path):
                    doctype = DocumentType.FILE
                    if last_doc and last_doc.document_type == DocumentType.RFILE:
                        doctype = DocumentType.RFILE
                    last_doc = document.Document(
                        doctype, path, None, None, None
                    )
            else:
                if not last_doc or doc_url != last_doc.path:
                    last_doc = document.Document(
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


def run_repl(initial_ctx: ScrContext, args: list[str]) -> int:
    try:
        # run with initial args
        readline.set_auto_history(False)
        readline.add_history(shlex.join(args[1:]))
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
                    args_parsing.parse_args(ctx_new, args)
                except ScrSetupError as ex:
                    log(stable_ctx, Verbosity.ERROR, str(ex))
                    continue

                resolve_repl_defaults(ctx_new, stable_ctx, last_doc)
                ctx = ctx_new

                try:
                    setup(ctx)
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


def run_scr(args: list[str]) -> int:
    ctx = ScrContext(blank=True)
    if len(args) < 2:
        log_raw(
            Verbosity.ERROR,
            f"missing command line options. Consider {SCRIPT_NAME} --help"
        )
        return 1

    try:
        args_parsing.parse_args(ctx, args[1:])
        setup(ctx)
    except ScrSetupError as ex:
        log_raw(Verbosity.ERROR, str(ex))
        return 1
    if ctx.repl:
        ec = run_repl(ctx, args)
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
        sys.exit(run_scr(sys.argv))
    except BrokenPipeError:
        # Python flushes standard streams on exit; redirect remaining output
        # to devnull to avoid another BrokenPipeError at shutdown
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
