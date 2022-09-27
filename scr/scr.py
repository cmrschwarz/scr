#!/usr/bin/env python3
from datetime import datetime
from typing import IO, Any, Optional, BinaryIO, Union, cast

import shutil
from io import BytesIO
import shlex
import lxml
import lxml.etree
import lxml.html
import pyrfc6266
import requests
import sys
import re
import os
from string import Formatter
import urllib.parse
from random_user_agent.user_agent import UserAgent
import pyparsing.exceptions

import pathlib

from http.cookiejar import MozillaCookieJar
from selenium.webdriver.remote.webelement import WebElement as SeleniumWebElement
import selenium.webdriver.common.by
from selenium.webdriver.remote.webdriver import WebDriver as SeleniumWebDriver
from selenium.common.exceptions import WebDriverException as SeleniumWebDriverException
from selenium.common.exceptions import TimeoutException as SeleniumTimeoutException
# see selenium_setup for why we have this
from urllib3.exceptions import MaxRetryError as SeleniumMaxRetryError
import time
import tempfile
import warnings
import urllib.request
from .utils import not_none
from .definitions import (
    T, K, DocumentDuplication, ScrSetupError, ScrFetchError, ScrMatchError, Verbosity, SCRIPT_NAME,
    SeleniumVariant, SeleniumStrategy, SeleniumDownloadStrategy,
    DocumentType, InteractiveResult,
    verbosities_display_dict, document_type_display_dict,
    DEFAULT_CSF, DEFAULT_CWF, DEFAULT_CPF, SCR_USER_AGENT,
    FILENAME_REQUIRING_FORMAT_SPECIFIERS

)
from .input_sequences import (
    OptionIndicatingStrings, YES_INDICATING_STRINGS, NO_INDICATING_STRINGS,
    EDIT_INDICATING_STRINGS, DOC_SKIP_INDICATING_STRINGS, CHAIN_SKIP_INDICATING_STRINGS,
    INSPECT_INDICATING_STRINGS, SKIP_INDICATING_STRINGS, set_join
)
from . import (
    document, selenium_setup, utils, config_data_class, args_parsing, download_job,
    locator, content_match, match_chain, scr_context, backslashescape
)

if utils.is_windows():
    from pyreadline3 import Readline
    readline: Readline = Readline()
else:
    import readline as rl
    readline = rl


class OutputFormatter:
    _args_dict: dict[str, Any]
    _args_list: list[Any]
    _format_parts: list[tuple[str, Union[str, None],
                              Union[str, None], Union[str, None]]]
    _out_stream: Union['download_job.PrintOutputStream', 'download_job.ByteBuffer', IO[bytes]]
    _found_stream: bool = False
    _input_buffer_sizes: int

    def __init__(
        self, format_str: str, cm: 'content_match.ContentMatch',
        out_stream: Union['download_job.PrintOutputStream', 'download_job.ByteBuffer', IO[bytes]],
        content: Union[str, bytes, 'download_job.MinimalInputStream', BinaryIO, None],
    ) -> None:
        self._args_dict = content_match_build_format_args(cm, content)
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
                (text, key, format_args, _b) = self._format_parts.pop()
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

        assert not self._format_parts
        self._out_stream.flush()
        return False


def dict_update_unless_none(current: dict[K, Any], updates: dict[K, Any]) -> None:
    current.update({
        k: v for k, v in updates.items() if v is not None
    })


def apply_general_format_args(
    doc: 'document.Document', mc: 'match_chain.MatchChain',
    args_dict: dict[str, Any], ci: Optional[int]
) -> None:
    dict_update_unless_none(args_dict, {
        "denc": doc.encoding,
        "cesc": mc.content_escape_sequence,
        "dl":   doc.path,
        "chain": mc.chain_id,
        "di": mc.di,
        "ci": ci
    })


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
    cm: 'content_match.ContentMatch',
    content: Any = None,
) -> dict[str, Any]:
    args_dict: dict[str, Any] = {}
    apply_general_format_args(cm.doc, cm.mc, args_dict, ci=cm.ci)
    apply_filename_format_args(cm.filename, args_dict)
    if content is not None:
        args_dict["c"] = content

    for lm in [cm.doc.locator_match, cm.llm, cm.clm]:
        if lm is not None:
            args_dict.update(lm.match_args)

    return args_dict


def check_log_message_needed(ctx: 'scr_context.ScrContext', verbosity: Verbosity) -> bool:
    if verbosity == Verbosity.ERROR:
        ctx.error_code = 1
    return ctx.verbosity is None or ctx.verbosity >= verbosity


def get_log_str(verbosity: Verbosity, msg: str) -> str:
    return verbosities_display_dict[verbosity] + msg + "\n"


def log_raw(msg: str) -> None:
    sys.stderr.write(msg)


def log(ctx: 'scr_context.ScrContext', verbosity: Verbosity, msg: str) -> None:
    if check_log_message_needed(ctx, verbosity):
        log_raw(get_log_str(verbosity, msg))


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
    conf: config_data_class.ConfigDataClass, attrib_path: list[str],
    dummy_cm: 'content_match.ContentMatch',
    unescape: bool, has_content: bool = False
) -> None:
    try:
        known_keys = content_match_build_format_args(
            dummy_cm, "" if has_content else None
        )
        unnamed_key_count = 0
        fmt_keys = get_format_string_keys(conf.resolve_attrib_path(
            attrib_path,
            backslashescape.unescape_string if unescape else None
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
                # TODO: maybe add some context dependant clues here
                # example: no {fn} if you forget cl
                raise ScrSetupError(
                    f"unavailable key '{{{k}}}' in {conf.get_configuring_argument(attrib_path)}"
                )
    except (re.error, ValueError) as ex:
        raise ScrSetupError(
            f"{str(ex)} in {conf.get_configuring_argument(attrib_path)}"
        )

# we need ctx because mc.ctx is stil None before we apply_defaults


def gen_default_format(mc: 'match_chain.MatchChain') -> str:
    form = "dl_"
    # if max was not set it is 'inf' which has length 3 which is a fine default
    mcc = len(mc.ctx.match_chains)
    if mcc > 1:
        form += f"{{chain:{len(str(mcc))}}}_"

    didigits = max(len(str(mc.dimin)), len(str(mc.dimax)))
    cidigits = max(len(str(mc.dimin)), len(str(mc.dimax)))
    if mc.ci_continuous:
        form += f"{{ci:0{cidigits}}}"
    elif mc.loc_content.multimatch:
        if mc.has_document_matching:
            form += f"{{di:0{didigits}}}_{{ci:0{cidigits}}}"
        else:
            form += f"{{ci:0{cidigits}}}"

    elif mc.has_document_matching:
        form += f"{{di:0{didigits}}}"
    return form


def mc_context(mc: 'match_chain.MatchChain', ctx: 'scr_context.ScrContext') -> str:
    if len(ctx.match_chains) <= 1 or mc.chain_id is None:
        return ""
    else:
        return f"match chain {mc.chain_id}: "


def setup_match_chain(mc: 'match_chain.MatchChain', ctx: 'scr_context.ScrContext') -> None:
    mc.apply_defaults(ctx.defaults_mc)
    mc.ci = mc.cimin
    mc.di = mc.dimin

    if mc.dimin > mc.dimax:
        raise ScrSetupError(f"{mc_context(mc, ctx)}dimin can't exceed dimax")
    if mc.cimin > mc.cimax:
        raise ScrSetupError(f"{mc_context(mc, ctx)}cimin can't exceed cimax")

    if mc.content_write_format is not None and mc.content_save_format is None:
        mc.content_save_format = DEFAULT_CSF

    if mc.content_forward_chains and mc.content_forward_format is None:
        mc.content_forward_format = DEFAULT_CWF

    if mc.prefer_parent_document_scheme is None:
        mc.prefer_parent_document_scheme = True

    if mc.file_base is None:
        mc.file_base = urllib.parse.urlparse(".")
    else:
        _, mc.file_base = normalize_link(
            cast(str, mc.file_base), urllib.parse.urlparse("."),
            DocumentType.FILE, mc.default_document_scheme,
            mc.prefer_parent_document_scheme, mc.force_document_scheme, False
        )
    if mc.url_base is not None:
        _, mc.url_base = normalize_link(
            cast(str, mc.url_base), None, DocumentType.URL, mc.default_document_scheme,
            mc.prefer_parent_document_scheme,
            mc.force_document_scheme, True
        )

    if not mc.document_output_chains:
        mc.document_output_chains = [mc]

    if mc.save_path_interactive and mc.content_save_format is not None:
        mc.content_save_format = ""

    locators = [mc.loc_content, mc.loc_label, mc.loc_document]
    for loc in locators:
        loc.setup(mc)

    if mc.loc_label.is_active():
        mc.has_label_matching = True
    if mc.loc_document.is_active():
        mc.has_document_matching = True
    if mc.loc_label.interactive or mc.loc_content.interactive:
        mc.has_interactive_matching = True

    content_output_variants = [
        mc.content_print_format,
        mc.content_save_format,
        mc.content_shell_command_format,
        mc.content_forward_format
    ]

    if mc.has_label_matching or mc.loc_content.is_active():
        mc.has_content_matching = True
    elif any(content_output_variants):
        mc.has_content_matching = True

    uses_output = any(cov is not None for cov in content_output_variants)
    if mc.has_content_matching and not uses_output:
        mc.content_print_format = DEFAULT_CPF
        uses_output = True

    if not mc.has_content_matching and not mc.has_document_matching:
        if mc.chain_id == 0:
            if not mc.ctx.repl and not mc.ctx.special_args_occured:
                mc.content_print_format = DEFAULT_CWF
                mc.has_content_matching = True
        else:
            raise ScrSetupError(
                f"match chain {mc.chain_id} has neither matching nor output format specifications"
            )

    dummy_cm = mc.gen_dummy_content_match(not mc.content_raw)
    if mc.content_print_format is not None:
        validate_format(mc, ["content_print_format"], dummy_cm, True, True)

    if mc.content_shell_command_format is not None:
        validate_format(mc, ["content_shell_command_format"], dummy_cm, True, False)
        if mc.content_shell_command_stdin_format is not None:
            validate_format(mc, ["content_shell_command_stdin_format"], dummy_cm, True, True)
    elif mc.content_shell_command_stdin_format is not None:
        raise ScrSetupError(
            f"{mc_context(mc, ctx)}cannot specify cshif without cshf: {mc.get_configuring_argument(['content_shell_command_stdin_format'])}"
        )
    if mc.content_forward_format is not None:
        validate_format(mc, ["content_forward_format"], dummy_cm, True, True)

    if mc.content_save_format is not None:
        if mc.content_save_format == "":
            raise ScrSetupError(
                f"{mc_context(mc, ctx)}csf cannot be the empty string: {mc.get_configuring_argument(['content_save_format'])}"
            )
        validate_format(mc, ["content_save_format"], dummy_cm, True, False)
        if mc.content_write_format is None:
            mc.content_write_format = DEFAULT_CWF
        else:
            validate_format(mc, ["content_write_format"], dummy_cm, True, True)

    if not mc.has_label_matching:
        mc.label_allow_missing = True
        if mc.labels_inside_content:
            raise ScrSetupError(
                f"{mc_context(mc, ctx)}cannot specify lic without lx or lr"
            )
    default_format: Optional[str] = None

    if mc.label_default_format is None:
        if mc.label_allow_missing and mc.need_label:
            if default_format is None:
                default_format = gen_default_format(mc)
            mc.label_default_format = default_format
    else:
        validate_format(mc, ["label_default_format"], dummy_cm, True, False)

    output_formats = [
        mc.content_print_format,
        mc.content_shell_command_format,
        mc.content_shell_command_stdin_format,
        mc.content_save_format,
        mc.content_write_format,
        mc.content_forward_format
    ]

    # because of lin / csin
    mc.need_filename_for_interaction = mc.loc_label.needs_filename() or format_string_args_occurence(
        mc.content_save_format, FILENAME_REQUIRING_FORMAT_SPECIFIERS
    ) > 0

    mc.need_filename = mc.need_filename_for_interaction or format_strings_args_occurence(
        output_formats, FILENAME_REQUIRING_FORMAT_SPECIFIERS
    ) > 0

    mc.need_content = format_strings_args_occurence(
        output_formats, ["c"]
    ) > 0

    mc.need_xml = any(loc.last_xml_needing_step is not None for loc in locators)

    mc.need_label = format_strings_args_occurence(
        output_formats, ["l"]
    ) > 0

    mc.need_output_multipass = any(
        format_string_arg_occurence(of, "c") > 1 for of in output_formats
    )

    if mc.filename_default_format is None:
        if mc.need_filename:
            default_format = gen_default_format(mc)
            mc.filename_default_format = default_format + ".dat"
    else:
        fn = dummy_cm.filename
        dummy_cm.filename = None
        validate_format(mc, ["filename_default_format"], dummy_cm, True, False)
        dummy_cm.filename = fn


def load_cookie_jar(ctx: 'scr_context.ScrContext') -> None:
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


def setup_ctx(ctx: 'scr_context.ScrContext') -> None:
    if ctx.tor_browser_dir:
        if ctx.selenium_variant is None:
            ctx.selenium_variant = SeleniumVariant.TORBROWSER
    elif ctx.selenium_headless:
        if ctx.selenium_variant is None:
            ctx.selenium_variant = SeleniumVariant.default()
    ctx.apply_defaults(scr_context.ScrContext())
    load_cookie_jar(ctx)

    if ctx.user_agent is not None and ctx.user_agent_random:
        raise ScrSetupError("the options ua and uar are incompatible")
    elif ctx.user_agent_random:
        ctx.user_agent = get_random_user_agent()
    elif ctx.user_agent is None and not ctx.selenium_variant.enabled():
        ctx.user_agent = SCR_USER_AGENT

    if ctx.enable_status_reports is None:
        ctx.enable_status_reports = sys.stdout.isatty()

    # if no chains are specified, use the origin chain as chain 0
    if not ctx.match_chains:
        ctx.match_chains = [ctx.origin_mc]
        ctx.origin_mc.chain_id = 0

    for d in ctx.docs:
        if d.expand_match_chains_above is not None:
            d.match_chains.extend(
                ctx.match_chains[d.expand_match_chains_above:]
            )
    for mc in ctx.match_chains:
        setup_match_chain(mc, ctx)

    for d in ctx.docs:
        mc0 = d.match_chains[0]
        force_mc_base = d.match_chains[0].force_mc_base
        use_path_as_base = not force_mc_base and d.document_type in [DocumentType.URL, DocumentType.FILE]
        use_file_base = d.document_type in [DocumentType.FILE, DocumentType.STRING]
        if not use_path_as_base:
            if use_file_base:
                mc0_base = cast(Optional[urllib.parse.ParseResult],  mc0.file_base)
            else:
                mc0_base = cast(Optional[urllib.parse.ParseResult], mc0.url_base)
            d.base = mc0_base
        for mc in d.match_chains[1:]:
            if mc.force_mc_base != force_mc_base:
                raise ScrSetupError(
                    f"match chains {mc0.chain_id} and {mc.chain_id} can't have different fbase values while sharing documents"
                )
            if use_path_as_base:
                continue
            if use_file_base:
                base = mc.file_base
            else:
                base = mc.url_base
            if d.base != base:
                raise ScrSetupError(
                    f"match chains {mc0.chain_id} and {mc.chain_id} can't have different {'' if use_file_base else 'r'}base values while sharing documents"
                )
        if d.path is not None:
            linktype = d.document_type
            if linktype != DocumentType.URL:
                linktype = DocumentType.FILE

            if d.document_type.non_r_type() in [DocumentType.FILE, DocumentType.STRING]:
                doc_base = cast(Optional[urllib.parse.ParseResult],  mc0.file_base)
            else:
                doc_base = cast(Optional[urllib.parse.ParseResult],  mc0.url_base)
            d.path, d.path_parsed = normalize_link(
                d.path, doc_base, linktype,
                mc0.default_document_scheme,
                mc0.prefer_parent_document_scheme,
                mc.force_document_scheme, True
            )
            if use_path_as_base:
                assert d.path_parsed is not None
                d.base = get_path_base(d.path_parsed)

        canonical_url = d.canonical_url()
        for mc in d.match_chains:
            mc.requested_document_urls.add(canonical_url)

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
        selenium_setup.setup_selenium(ctx)

    if ctx.dl_manager is None and ctx.max_download_threads != 0:
        ctx.dl_manager = download_job.DownloadManager(
            ctx, ctx.max_download_threads
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


def gen_dl_temp_name(
    ctx: 'scr_context.ScrContext', final_filepath: Optional[str]
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


def fetch_file(ctx: 'scr_context.ScrContext', path: str, stream: bool = False) -> Union[bytes, BinaryIO]:
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


def try_read_data_url(cm: 'content_match.ContentMatch') -> Optional[bytes]:
    assert cm.url_parsed is not None
    if cm.url_parsed.scheme == "data":
        res = urllib.request.urlopen(
            cm.clm.text,
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
    if isinstance(ex, requests.exceptions.ConnectTimeout) or isinstance(ex, requests.ReadTimeout):
        return ScrFetchError("connection timeout")
    return ScrFetchError("connection failed")


def request_raw(
    ctx: 'scr_context.ScrContext', path: str, path_parsed: urllib.parse.ParseResult,
    cookie_dict: Optional[dict[str, dict[str, dict[str, Any]]]] = None,
    proxies: Optional[dict[str, str]] = None, stream: bool = False
) -> requests.Response:
    hostname = path_parsed.hostname if path_parsed.hostname else ""
    if cookie_dict is None:
        cookie_dict = ctx.cookie_dict
    cookies = {
        name: ck["value"]
        for name, ck in cookie_dict.get(hostname, {}).items()
    }
    assert ctx.user_agent is not None
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
    except pyparsing.exceptions.ParseException:
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
    ctx: 'scr_context.ScrContext', path: str,
    path_parsed: urllib.parse.ParseResult,


) -> tuple[Union['download_job.MinimalInputStream', bytes, None], Optional[str]]:
    try:
        req = request_raw(ctx, path, path_parsed)
        data = req.content
        encoding = req.encoding
        req.close()
        return data, encoding
    except requests.exceptions.RequestException as ex:
        raise request_exception_to_scr_fetch_error(ex)


def build_xpath_string(text: str) -> str:
    pos_single_quote = text.find("'")
    if pos_single_quote == -1:
        return f"'{text}'"
    pos_double_quote = text.find('"')
    if pos_double_quote == -1:
        return f'"{text}"'
    # since xpath does not have escaping, if we have both types of
    # quotes in our string we need to express it using concat()
    if pos_single_quote < pos_double_quote:
        head = f'"{text[:pos_double_quote]}"'
        tail = text[pos_double_quote:]
    else:
        head = f"'{text[:pos_single_quote]}'"
        tail = text[pos_single_quote:]
    return f'concat({head},{build_xpath_string(tail)})'


def build_elem_xpath(root: 'lxml.html.HtmlElement', elem: 'lxml.html.HtmlElement') -> str:
    id = elem.get("id")
    if id is not None:
        return f"//{elem.tag}[@id={build_xpath_string(id)}]"
    res = ""
    while True:
        parent = cast(Optional[lxml.html.HtmlElement], elem.getparent())
        index = 1
        if parent is not None:
            for e in parent.iterchildren():
                if e == elem:
                    break
                if e.tag == elem.tag:
                    index += 1
        res = f"/{elem.tag}[{index}]{res}"
        if elem == root:
            return res
        assert parent is not None
        elem = parent


def get_child_frames(elem: 'lxml.html.HtmlElement') -> list['lxml.html.HtmlElement']:
    res = []
    frame_types = ["iframe", "embed", "object"]
    for ft in frame_types:
        res += cast(list[lxml.html.HtmlElement], elem.xpath(f"//{ft}"))
    return res


def insert_shadow_roots(
    ctx: 'scr_context.ScrContext', doc_xml: lxml.html.HtmlElement,
    shadow_root_tree: Any, nested: bool = False
) -> None:
    xpath = shadow_root_tree[0]
    inner_html = shadow_root_tree[1]
    children = shadow_root_tree[2]
    if nested:
        xpath = "/html/" + xpath
    elem = doc_xml.xpath(xpath)
    if len(elem) != 1:
        log(ctx, Verbosity.WARN, "failed to match up shadow roots")
        return
    elem = elem[0]
    shadow_root_xml = cast(
        lxml.html.HtmlElement, lxml.html.fromstring(inner_html)
    )
    for c in children:
        insert_shadow_roots(ctx, shadow_root_xml, c, True)
    elem.append(shadow_root_xml)


def expand_shadow_roots(
    ctx: 'scr_context.ScrContext', doc_xml: lxml.html.HtmlElement
) -> bool:
    script = """
    function build_xpath(el) {
        const tag_name = el.tagName.toLowerCase();
        if (el.parentElement === null) return "/" + tag_name;
        var ci = 0;
        for (const c of el.parentNode.childNodes) {
            if (c === el) return build_xpath(el.parentNode) + '/' + tag_name + '[' + (ci + 1) + ']';
            if (c.nodeType == Node.ELEMENT_NODE && c.tagName.toLowerCase() == tag_name) ci++;
        }
    }
    function collect_shadow_roots(node) {
        var res = [];
        for (const e of node.querySelectorAll('*')) {
            if (e.shadowRoot === null) continue;
            res.push([build_xpath(e), e.shadowRoot.innerHTML, collect_shadow_roots(e.shadowRoot)]);
        }
        return res;
    }
    return collect_shadow_roots(document);
    """
    shadow_root_tree = selenium_setup.selenium_exec_script(ctx, script)
    if len(shadow_root_tree) == 0:
        return False
    for srt in shadow_root_tree:
        insert_shadow_roots(ctx, doc_xml, srt)
    return True


def expand_child_frames(
    ctx: 'scr_context.ScrContext', text: str, doc_xml: lxml.html.HtmlElement
) -> tuple[str, lxml.html.HtmlElement]:
    drv = cast(SeleniumWebDriver, ctx.selenium_driver)
    roots_expanded = expand_shadow_roots(ctx, doc_xml)
    frames: list[lxml.html.HtmlElement] = get_child_frames(doc_xml)
    if not frames:
        if roots_expanded:
            text = cast(str, lxml.html.tostring(doc_xml))
        return text, doc_xml
    depth = 0
    curr_xml = doc_xml
    try:
        frame_stack: list[tuple[
            SeleniumWebElement, int, lxml.html.HtmlElement
        ]] = []
        while True:
            for frame in reversed(frames):
                frame_xpath = build_elem_xpath(curr_xml, frame)
                frames_sel = drv.find_elements(
                    by=selenium.webdriver.common.by.By.XPATH,
                    value=frame_xpath
                )
                if len(frames_sel) != 1:
                    log(ctx, Verbosity.WARN, "failed to match up iframe contents")
                else:
                    frame_stack.append((frames_sel[0], depth + 1, frame))
            if not frame_stack:
                break
            iframe_sel, depth_new, curr_xml = frame_stack.pop()
            while depth_new <= depth:
                depth -= 1
                drv.switch_to.parent_frame()
            drv.switch_to.frame(iframe_sel)
            depth = depth_new
            frame_xml = cast(
                lxml.html.HtmlElement, lxml.html.fromstring(drv.page_source)
            )
            expand_shadow_roots(ctx, frame_xml)
            frames = get_child_frames(frame_xml)
            curr_xml.append(frame_xml)
            curr_xml = frame_xml

        return cast(str, lxml.html.tostring(doc_xml)), doc_xml
    except SeleniumWebDriverException:
        # if the document fundamentally changes while we do this, we might
        # end up trying to focus on a deleted iframe
        # in that case we just give up on the iframe sources for this iteration
        return text, doc_xml
    finally:
        drv.switch_to.default_content()


def selenium_get_full_page_source(ctx: 'scr_context.ScrContext') -> tuple[str, lxml.html.HtmlElement]:
    text = cast(SeleniumWebDriver, ctx.selenium_driver).page_source
    doc_xml = cast(lxml.html.HtmlElement, lxml.html.fromstring(text))
    return expand_child_frames(ctx, text, doc_xml)


def fetch_doc(ctx: 'scr_context.ScrContext', doc: 'document.Document') -> None:
    if ctx.selenium_variant.enabled():
        if doc is not ctx.reused_doc or ctx.changed_selenium:
            log(
                ctx, Verbosity.INFO,
                f"getting selenium page source for {document_type_display_dict[doc.document_type]} '{doc.path}'"
            )
            selpath = doc.path
            # TODO: handle string docs
            assert selpath is not None
            assert doc.path_parsed is not None
            if doc.document_type in [DocumentType.FILE, DocumentType.RFILE]:
                selpath = "file:" + os.path.abspath(selpath)

            fetch_begin = datetime.now()
            try:
                cast(SeleniumWebDriver, ctx.selenium_driver).get(selpath)
            except SeleniumTimeoutException:
                raise ScrFetchError("selenium timeout")
            except SeleniumWebDriverException as ex:
                try:
                    if (
                        doc.document_type == DocumentType.URL
                        and os.path.exists(doc.path_parsed.path)
                    ):
                        raise ScrFetchError("not found, possibly file misrepresented, as url")
                except IOError:
                    pass
                raise ex
            while (datetime.now() - fetch_begin).total_seconds() < ctx.request_timeout_seconds:
                try:
                    result = selenium_setup.selenium_exec_script(ctx, "return document.readyState == 'complete';")
                    if result is True:
                        break
                    time.sleep(0)
                except SeleniumTimeoutException:
                    raise ScrFetchError("selenium timeout")
                except SeleniumWebDriverException as ex:
                    raise ex
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

    doc_base_type = doc.document_type.non_r_type()
    if doc_base_type == DocumentType.STRING:
        return
    assert doc.path is not None
    assert doc.path_parsed is not None
    if doc_base_type == DocumentType.FILE:
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


def gen_final_content_format(format_str: str, cm: 'content_match.ContentMatch') -> bytes:
    with BytesIO(b"") as buf:
        of = OutputFormatter(format_str, cm, buf, None)
        while of.advance():
            pass
        buf.seek(0)
        res = buf.read()
    return res


def get_ci_di_context(cm: 'content_match.ContentMatch') -> str:
    if cm.mc.has_document_matching:
        if cm.mc.loc_content.multimatch:
            di_ci_context = f" (di={cm.di}, ci={cm.ci})"
        else:
            di_ci_context = f" (di={cm.di})"
    elif cm.mc.loc_content.multimatch:
        di_ci_context = f" (ci={cm.ci})"
    else:
        di_ci_context = ""
    return di_ci_context


def get_content_type_label(cm: 'content_match.ContentMatch') -> str:
    return "content match" if cm.mc.content_raw else "content link"


def forward_document(ctx: 'scr_context.ScrContext', doc: Optional['document.Document']) -> None:
    if doc is None:
        return
    ctx.docs.append(doc)


def handle_content_match(cm: 'content_match.ContentMatch') -> InteractiveResult:
    cm.di = cm.mc.di
    cm.ci = cm.mc.ci
    cm.mc.loc_content.apply_order_dependant_steps(cm.clm)
    cm.mc.ci += 1

    di_ci_context = get_ci_di_context(cm)
    content_type = get_content_type_label(cm)

    if cm.llm is not None:
        label_context = f' (label match was "{cm.llm.text}")'
    else:
        if cm.mc.need_label:
            label_context = " (no label match)"
        else:
            label_context = ""

    while True:
        if not cm.mc.content_raw:
            cm.clm.text, cm.url_parsed = normalize_link(
                cm.clm.text, cm.base, cm.doc.document_type.derived_link_type(),
                cm.mc.default_document_scheme,
                cm.mc.prefer_parent_document_scheme,
                cm.mc.force_document_scheme, False
            )

        if cm.mc.loc_content.interactive:
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
                prompt_msg = f'"{cm.doc.path}"{di_ci_context}{label_context}: accept {content_type} "{cm.clm.text}"'

            res = prompt(
                f'{prompt_msg} [Yes/no/edit{inspect_opt_str}/chainskip/docskip]? ',
                prompt_options,
                InteractiveResult.ACCEPT
            )
            if res is InteractiveResult.ACCEPT:
                break
            if res == InteractiveResult.INSPECT:
                print(
                    f'content for "{cm.doc.path}"{label_context}:\n' + cm.clm.text)
                continue
            if res is not InteractiveResult.EDIT:
                return res
            if not cm.mc.content_raw:
                cm.clm.text = input(f"enter new {content_type}:\n")
            else:
                print(
                    f'enter new {content_type} (terminate with a newline followed by the string "{cm.mc.content_escape_sequence}"):\n')
                cm.clm.text = ""
                while True:
                    cm.clm.text += input() + "\n"
                    i = cm.clm.text.find(
                        "\n" + cm.mc.content_escape_sequence)
                    if i != -1:
                        cm.clm.text = cm.clm.text[:i]
                        break
        break

    job = download_job.DownloadJob(cm)
    res = job.handle_user_interaction()
    if res != InteractiveResult.ACCEPT:
        return res
    if cm.mc.ctx.dl_manager is not None:
        if job.warrants_background_task():
            cm.mc.ctx.dl_manager.submit(job)
        else:
            job.request_print_streams(cm.mc.ctx.dl_manager.pom)
            forward_document(cm.mc.ctx, job.run_job())
    else:
        forward_document(cm.mc.ctx, job.run_job())

    return InteractiveResult.ACCEPT


def handle_document_match(mc: 'match_chain.MatchChain', doc: 'document.Document') -> InteractiveResult:
    if not mc.loc_document.interactive:
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
    mc: 'match_chain.MatchChain', doc: 'document.Document'
) -> tuple[list['content_match.ContentMatch'], int]:
    # TODO: properly set content match base respecting iframes
    text = cast(str, doc.text)
    content_matches: list[content_match.ContentMatch] = []
    content_lms_xp: list[locator.LocatorMatch] = mc.loc_content.match_xpath(
        text, doc.xml, mc.has_content_xpaths
    )
    label_lms: list[locator.LocatorMatch] = []
    if mc.has_label_matching and not mc.labels_inside_content:
        label_lms = mc.loc_label.match_xpath(text, doc.xml, False)
        label_lms = mc.loc_label.apply_regex_matches(label_lms)
        label_lms = mc.loc_label.apply_js_matches(doc, mc, label_lms)
    match_index = 0
    labels_none_for_n = 0
    for clm_xp in content_lms_xp:
        if mc.labels_inside_content and mc.loc_label.xpath and mc.loc_content.xpath:
            label_lms = mc.loc_label.match_xpath(
                clm_xp.result, clm_xp.xmatch_xml, False
            )
            # in case we have label xpath matching, the label regex matching
            # will be done on the LABEL xpath result, not the content one
            # even for lic = y
            label_lms = mc.loc_label.apply_regex_matches(label_lms)
            label_lms = mc.loc_label.apply_js_matches(doc, mc, label_lms)

        content_lms = mc.loc_content.apply_regex_matches([clm_xp])
        content_lms = mc.loc_content.apply_js_matches(doc, mc, content_lms)
        for clm in content_lms:
            llm: Optional[locator.LocatorMatch] = None
            if mc.labels_inside_content:
                if not mc.loc_label.xpath or not mc.loc_content.xpath:
                    llm = locator.LocatorMatch()
                    llm.result = clm.result
                    if mc.loc_label.xpath:
                        try:
                            res_xml = cast(lxml.html.HtmlElement, lxml.html.fromstring(clm.result))
                            label_lms = mc.loc_label.match_xpath(clm.result, res_xml)
                        except lxml.etree.LxmlError:
                            label_lms = []
                    else:
                        label_lms = [llm]

                    label_lms = mc.loc_label.apply_regex_matches(label_lms, False)
                    label_lms = mc.loc_label.apply_js_matches(
                        doc, mc, label_lms, False
                    )
                if len(label_lms) == 0:
                    if not mc.label_allow_missing:
                        labels_none_for_n += 1
                        continue
                else:
                    llm = label_lms[0]
            else:
                if not mc.loc_label.multimatch and len(label_lms) > 0:
                    llm = label_lms[0]
                elif match_index < len(label_lms):
                    llm = label_lms[match_index]
                elif not mc.label_allow_missing:
                    labels_none_for_n += 1
                    continue
                else:
                    llm = None

            content_matches.append(
                content_match.ContentMatch(clm, llm, mc, doc)
            )
        match_index += 1
    return content_matches, labels_none_for_n


def gen_document_matches(
    mc: 'match_chain.MatchChain', doc: 'document.Document'
) -> list['document.Document']:
    document_matches = []
    document_lms = mc.loc_document.match_xpath(
        cast(str, doc.text), doc.xml, False
    )
    document_lms = mc.loc_document.apply_regex_matches(document_lms)
    document_lms = mc.loc_document.apply_js_matches(doc, mc, document_lms)
    for dlm in document_lms:
        mc.loc_document.apply_format_for_document_match(doc, mc, dlm)
        link_type = doc.document_type.derived_link_type()
        path, path_parsed = normalize_link(
            dlm.result, doc.base, link_type, mc.default_document_scheme,
            mc.prefer_parent_document_scheme,
            mc.force_document_scheme, False
        )
        if mc.document_duplication != DocumentDuplication.ALLOWED:
            canonical_url = urllib.parse.urlunparse(path_parsed)
            if canonical_url in mc.requested_document_urls:
                if mc.document_duplication == DocumentDuplication.UNIQUE:
                    continue
                assert mc.document_duplication == DocumentDuplication.NONRECURSIVE
                parent = doc
                recursion_detected = False
                while True:
                    pcurl = parent.canonical_url()
                    if pcurl == canonical_url:
                        recursion_detected = True
                        break
                    if parent.parent_doc is None:
                        break
                    parent = parent.parent_doc
                if recursion_detected:
                    continue
            else:
                mc.requested_document_urls.add(canonical_url)

        document_matches.append(document.Document(
            document_type=link_type,
            path=path,
            src_mc=mc,
            parent_doc=doc,
            match_chains=mc.document_output_chains,
            expand_match_chains_above=None,
            locator_match=dlm,
            base=get_path_base(path_parsed),
            path_parsed=path_parsed
        ))

    return document_matches


def make_padding(ctx: 'scr_context.ScrContext', count_number: int) -> tuple[str, str]:
    content_count_pad_len = (
        ctx.selenium_content_count_pad_length
        - min(len(str(count_number)), ctx.selenium_content_count_pad_length)
    )
    rpad = int(content_count_pad_len / 2)
    lpad = content_count_pad_len - rpad
    return lpad * " ", rpad * " "


def handle_interactive_chains(
    ctx: 'scr_context.ScrContext',
    interactive_chains: list['match_chain.MatchChain'],
    doc: 'document.Document',
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

    msg = f"{ctx.last_doc_path}: use page with potentially"
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

    user_answered = False
    if try_number > 1:
        user_answered = utils.stdin_has_content(ctx.selenium_poll_frequency_secs)

    if not user_answered and msg_full:
        sys.stdout.write(msg_full)
        sys.stdout.flush()

    if not user_answered:
        user_answered = utils.stdin_has_content(ctx.selenium_poll_frequency_secs)
    result = None
    if user_answered:
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


def match_chain_was_satisfied(mc: 'match_chain.MatchChain') -> tuple[bool, bool]:
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


def handle_match_chain(mc: 'match_chain.MatchChain', doc: 'document.Document') -> None:
    if mc.need_content_matches():
        content_matches, mc.labels_none_for_n = gen_content_matches(
            mc, doc
        )
    else:
        content_matches = []

    if mc.need_document_matches(True):
        document_matches = gen_document_matches(mc, doc)
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
    mc: 'match_chain.MatchChain', doc: 'document.Document',
    content_skip_doc: bool, documents_skip_doc: bool,
    new_docs: list['document.Document']
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


def get_path_base(link: urllib.parse.ParseResult) -> Optional[urllib.parse.ParseResult]:
    if link.scheme == "data":
        return None
    return link._replace(path=os.path.dirname(link.path))


def normalize_link(
    link: str,
    base: Optional[urllib.parse.ParseResult],
    link_type: 'DocumentType',
    default_scheme: str,
    prefer_parent_scheme: bool,
    force_default_scheme: bool,
    prefer_parsing_as_absolute_url: bool,
) -> tuple[str, urllib.parse.ParseResult]:
    link = link.strip()
    if link.startswith("data:"):
        return link, urllib.parse.urlparse(link)
    if link_type == DocumentType.FILE:
        assert base is not None
        if link.startswith("file:"):
            link = utils.remove_file_scheme_from_url(link)
        if not os.path.isabs(link):
            # attempt to preserve short, relative paths were possible
            if os.path.abspath(base.path) == os.path.abspath(link):
                link = base.path
            else:
                link = os.path.normpath(os.path.join(base.path, link))
        else:
            link = os.path.normpath(link)
        return link, urllib.parse.urlparse("file:" + link)._replace(scheme="")
    assert link_type == DocumentType.URL
    changed = False
    link_parsed = urllib.parse.urlparse(link)

    scheme_was_blank = link_parsed.scheme == ""
    if scheme_was_blank:
        if force_default_scheme:
            scheme = default_scheme
        elif prefer_parent_scheme and base is not None and base.scheme not in ["", "file"]:
            scheme = base.scheme
        else:
            scheme = default_scheme
        link_parsed = link_parsed._replace(
            scheme=scheme
        )
        changed = True

    # for urls like 'google.com' urllib makes this a path instead of a netloc
    # we change that when there would be no netloc otherwise, or when
    # this interpretation is explicitly preferred using the flag
    if link_parsed.netloc == "" and scheme_was_blank and (base is None or prefer_parsing_as_absolute_url):
        first_slash = link_parsed.path.find("/")
        if first_slash == -1:
            netloc = link_parsed.path
            path = ""
        else:
            # when the slash is right at the start, the netloc stays blank
            netloc = link_parsed.path[0:first_slash]
            path = link_parsed.path[first_slash:]
        link_parsed = link_parsed._replace(netloc=netloc, path=path)
        changed = True

    if base is not None:
        if link_parsed.netloc == "" and scheme_was_blank:
            link_parsed = link_parsed._replace(netloc=base.netloc)
            lnk_ppp = pathlib.PurePosixPath(link)
            if not lnk_ppp.is_absolute() and base.path:
                du_ppp = pathlib.PurePosixPath(base.path)
                lnk_ppp = du_ppp.parent.joinpath(lnk_ppp)
                link_parsed = link_parsed._replace(path=str(lnk_ppp))
                changed = True

    if changed:
        link = urllib.parse.urlunparse(link_parsed)
    return link, link_parsed


def parse_xml(ctx: 'scr_context.ScrContext', doc: 'document.Document') -> None:
    try:
        text = cast(str, doc.text)
        if text.strip() == "":
            src_xml = lxml.html.Element("html")
        elif doc.forced_encoding:
            src_bytes = text.encode(cast(str, doc.encoding), errors="surrogateescape")
            src_xml = cast(lxml.html.HtmlElement, lxml.html.fromstring(
                src_bytes,
                parser=lxml.html.HTMLParser(encoding=doc.encoding)
            ))
        else:
            src_xml = cast(lxml.html.HtmlElement, lxml.html.fromstring(text))
        doc.xml = src_xml
    except (lxml.etree.LxmlError, UnicodeEncodeError, UnicodeDecodeError) as ex:
        log(ctx, Verbosity.ERROR, f"{doc.path}: failed to parse as xml: {str(ex)}")


def process_document_queue(ctx: 'scr_context.ScrContext') -> Optional['document.Document']:
    doc = None
    while ctx.docs:
        doc = ctx.docs.popleft()
        ctx.last_doc_path = doc.path
        unsatisfied_chains = 0
        chains_needing_xml = 0
        for mc in doc.match_chains:
            if mc.need_document_matches(False) or mc.need_content_matches():
                unsatisfied_chains += 1
                mc.satisfied = False
                if mc.need_xml:
                    chains_needing_xml += 1
        if unsatisfied_chains == 0:
            if not ctx.selenium_variant.enabled() or (doc is ctx.reused_doc and not ctx.changed_selenium):
                continue

        try_number = 0
        try:
            fetch_doc(ctx, doc)
        except SeleniumWebDriverException as ex:
            if selenium_setup.selenium_has_died(ctx):
                selenium_setup.report_selenium_died(ctx)
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
                assert ctx.selenium_variant.enabled()
                try:
                    drv = cast(SeleniumWebDriver, ctx.selenium_driver)
                    ctx.last_doc_path = drv.current_url
                    src_new, xml_new = selenium_get_full_page_source(ctx)
                    same_content = (src_new == doc.text)
                    doc.text = src_new
                    doc.xml = xml_new
                except SeleniumWebDriverException as ex:
                    if selenium_setup.selenium_has_died(ctx):
                        selenium_setup.report_selenium_died(ctx)
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
                    handle_match_chain(mc, doc)
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
                    ctx, interactive_chains, doc, try_number, last_msg
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


def try_close_selenium(ctx: 'scr_context.ScrContext') -> None:
    try:
        sd = cast(SeleniumWebDriver, ctx.selenium_driver)
        sd.quit()  # quit automatically closes all windows
    except (SeleniumWebDriverException, SeleniumMaxRetryError, OSError):
        pass
    finally:
        ctx.selenium_driver = None


def finalize(ctx: 'scr_context.ScrContext') -> None:
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

    if ctx.selenium_driver and not ctx.selenium_keep_alive and not selenium_setup.selenium_has_died(ctx):
        try_close_selenium(ctx)
    if ctx.downloads_temp_dir:
        try:
            shutil.rmtree(ctx.downloads_temp_dir)
        finally:
            ctx.downloads_temp_dir = None
    success = True


def resolve_repl_defaults(
    ctx_new: 'scr_context.ScrContext', ctx: 'scr_context.ScrContext',
    last_doc: Optional['document.Document']
) -> None:
    if ctx_new.user_agent_random and not ctx_new.user_agent:
        ctx.unfinalize_value(["user_agent"])

    if ctx_new.user_agent and not ctx_new.user_agent_random:
        ctx.unfinalize_value(["user_agent_random"])

    ctx_new.apply_defaults(ctx)

    if ctx_new.max_download_threads != ctx.max_download_threads:
        if ctx.dl_manager is not None:
            try:
                ctx.dl_manager.terminate()
            finally:
                ctx.dl_manager = None
    elif ctx.dl_manager is not None:
        ctx.dl_manager.reset()
    changed_selenium = False
    if ctx_new.selenium_variant != ctx.selenium_variant:
        changed_selenium = True
        ctx_new.selenium_driver = None
        if ctx.selenium_driver is not None:
            try_close_selenium(ctx)

    if ctx_new.selenium_driver:
        doc_url = None
        try:
            doc_url = ctx_new.selenium_driver.current_url
        except (SeleniumWebDriverException, SeleniumMaxRetryError):
            if selenium_setup.selenium_has_died(ctx_new):
                selenium_setup.report_selenium_died(ctx_new)
                last_doc = None
        if doc_url:
            if doc_url.startswith("file:"):
                path = utils.remove_file_scheme_from_url(doc_url)
                if not last_doc or os.path.abspath(not_none(last_doc.path)) != os.path.abspath(path):
                    doctype = DocumentType.FILE
                    if last_doc and last_doc.document_type == DocumentType.RFILE:
                        doctype = DocumentType.RFILE
                    last_doc = document.Document(doctype, path)
            else:
                if not last_doc or doc_url != last_doc.path:
                    last_doc = document.Document(DocumentType.URL, doc_url)
    for d in ctx_new.docs:
        d.parent_doc = last_doc
    if not ctx_new.docs and last_doc:
        last_doc.expand_match_chains_above = len(ctx_new.match_chains)
        last_doc.match_chains = list(ctx_new.match_chains)
        ctx_new.reused_doc = last_doc
        ctx_new.docs.append(last_doc)
    ctx_new.changed_selenium = changed_selenium
    if changed_selenium and last_doc:
        last_doc.text = None
        last_doc.xml = None


def run_repl(initial_ctx: 'scr_context.ScrContext', args: list[str]) -> int:
    success = False
    try:
        # run with initial args
        if not utils.is_windows():
            readline.set_auto_history(False)
        readline.add_history(shlex.join(args[1:]))
        tty = sys.stdout.isatty()
        stable_ctx = initial_ctx
        ctx: Optional['scr_context.ScrContext'] = initial_ctx
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
                    if line.strip():
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

                ctx_new = scr_context.ScrContext(blank=True)
                try:
                    args_parsing.parse_args(ctx_new, args)
                except ScrSetupError as ex:
                    log(stable_ctx, Verbosity.ERROR, str(ex))
                    continue

                resolve_repl_defaults(ctx_new, stable_ctx, last_doc)
                ctx = ctx_new

                try:
                    setup_ctx(ctx)
                except ScrSetupError as ex:
                    log(ctx, Verbosity.ERROR, str(ex))
                    if ctx.exit:
                        stable_ctx = ctx
                        return ctx.error_code
                    ctx = None
            except KeyboardInterrupt:
                print("")
                ctx = None
                continue
    finally:
        if not success:
            stable_ctx.abort = True
        finalize(stable_ctx)


def run_scr(args: list[str]) -> int:
    ctx = scr_context.ScrContext(blank=True)
    if len(args) < 2:
        log_raw(get_log_str(
            Verbosity.ERROR,
            f"missing command line options. Consider {SCRIPT_NAME} --help"
        ))
        return 1

    try:
        args_parsing.parse_args(ctx, args[1:])
        setup_ctx(ctx)
    except ScrSetupError as ex:
        log_raw(get_log_str(Verbosity.ERROR, str(ex)))
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
