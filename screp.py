#!/usr/bin/env python3
from argparse import ArgumentError
import lxml
import lxml.html
import requests
import sys
import select
import re
import os
from string import Formatter
import readline
import urllib.parse
from http.cookiejar import MozillaCookieJar
from random_user_agent.user_agent import UserAgent
from tbselenium.tbdriver import TorBrowserDriver
from selenium import webdriver
import selenium.webdriver.chrome.service
import selenium.webdriver.firefox.service
from selenium.common.exceptions import WebDriverException
from collections import deque
from enum import Enum, IntEnum
import time
import tempfile
import itertools
import warnings
import copy
import shlex
import binascii
import shutil
import mimetypes


def prefixes(str):
    return [str[:i] for i in range(len(str), 0, -1)]


yes_indicating_strings = prefixes("yes") + prefixes("true") + ["1", "+"]
no_indicating_strings = prefixes("no") + prefixes("false") + ["0", "-"]
skip_indicating_strings = prefixes("skip")
chain_skip_indicating_strings = prefixes("chainskip")
doc_skip_indicating_strings = prefixes("docskip")
edit_indicating_strings = prefixes("edit")
inspect_indicating_strings = prefixes("inspect")
accept_chain_indicating_strings = prefixes("acceptchain")
chain_regex = re.compile("^[0-9\\-\\*\\^]*$")

DEFAULT_CPF = "{content}\\n"
DEFAULT_CWF = "{content}"
# mimetype to use for selenium downloading to avoid triggering pdf viewers etc.
DUMMY_MIMETYPE = "application/zip"


class InteractiveResult(Enum):
    ACCEPT = 0
    REJECT = 1
    EDIT = 2
    INSPECT = 3
    SKIP_CHAIN = 4
    SKIP_DOC = 5
    ACCEPT_CHAIN = 6


class DocumentType(Enum):
    URL = 1
    FILE = 2
    RFILE = 3

    def derived_type(self):
        if self == DocumentType.RFILE:
            return DocumentType.URL
        return self

    def url_handling_type(self):
        if self == DocumentType.RFILE:
            return DocumentType.FILE
        return self


class SeleniumVariant(Enum):
    DISABLED = 0
    CHROME = 1
    FIREFOX = 2
    TORBROWSER = 3


selenium_variants_dict = {
    "disabled": SeleniumVariant.DISABLED,
    "tor": SeleniumVariant.TORBROWSER,
    "firefox": SeleniumVariant.FIREFOX,
    "chrome": SeleniumVariant.CHROME
}


class SeleniumDownloadStrategy(Enum):
    EXTERNAL = 0
    INTERNAL = 1
    FETCH = 2


selenium_download_strategies_dict = {
    "external": SeleniumDownloadStrategy.EXTERNAL,
    "internal": SeleniumDownloadStrategy.INTERNAL,
    "fetch": SeleniumDownloadStrategy.FETCH,
}


class SeleniumStrategy(Enum):
    DISABLED = 0
    FIRST = 1
    INTERACTIVE = 2
    DEDUP = 3


selenium_strats_dict = {
    "first": SeleniumStrategy.FIRST,
    "interactive": SeleniumStrategy.INTERACTIVE,
    "dedup": SeleniumStrategy.DEDUP,
}


class Verbosity(IntEnum):
    ERROR = 1
    WARN = 2
    INFO = 3
    DEBUG = 4


verbosities_dict = {
    "error": Verbosity.ERROR,
    "warn": Verbosity.WARN,
    "info": Verbosity.INFO,
    "debug": Verbosity.DEBUG,
}

verbosities_display_dict = {
    Verbosity.ERROR: "[ERROR]: ",
    Verbosity.WARN:  "[ WARN]: ",
    Verbosity.INFO:  "[ INFO]: ",
    Verbosity.DEBUG: "[DEBUG]: ",
}


class ContentMatch:
    def __init__(self, label_match, content_match):
        self.label_regex_match = label_match
        self.content_regex_match = content_match

    def __key(self):
        return (self.label_match.__key(), self.content)

    def __eq__(x, y):
        return isinstance(y, x.__class__) and x.__key() == y.__key()

    def __hash__(self):
        return hash(self.__key())


class RegexMatch:
    def __init__(self, value, group_list=[], group_dict={}):
        self.value = value
        self.group_list = [x if x is not None else "" for x in group_list]
        self.group_dict = {k: (v if v is not None else "")
                           for (k, v) in group_dict.items()}

    def __key(self):
        return [self.value] + self.group_list + sorted(self.group_dict.items())

    def __eq__(x, y):
        return isinstance(y, x.__class__) and x.__key() == y.__key()

    def __hash__(self):
        return hash(self.__key())


def empty_string_to_none(string):
    if string == "":
        return None
    return string


class Locator:
    def __init__(self, name, additional_format_keys=[], blank=False):
        self.name = name
        self.xpath = None
        self.regex = None
        self.format = None
        self.multimatch = True
        self.interactive = False
        self.content_capture_group = None
        self.additional_format_keys = additional_format_keys
        if blank:
            for k in self.__dict__:
                self.__dict__[k] = None

    def compile_regex(self):
        if self.regex is None:
            return
        try:
            regex_comp = re.compile(self.regex, re.MULTILINE)
        except re.error as err:
            error(f"{self.name[0]}r is not a valid regex: {err.msg}")
        if self.name in regex_comp.groupindex:
            self.content_capture_group = self.name
        else:
            self.content_capture_group = 0
        self.regex = regex_comp

    def setup(self):
        self.xpath = empty_string_to_none(self.xpath)
        self.regex = empty_string_to_none(self.regex)
        self.format = empty_string_to_none(self.format)
        if self.format:
            self.format = unescape_string(self.format, f"{self.name[0]}f")
        self.compile_regex()
        if self.format:
            try:
                if self.regex:
                    capture_group_keys = list(self.regex.groupindex.keys())
                    unnamed_regex_group_count = self.regex.groups - \
                        len(capture_group_keys)
                else:
                    capture_group_keys = []
                    unnamed_regex_group_count = 0
                known_keys = [self.name] + capture_group_keys + \
                    self.additional_format_keys
                key_count = len(known_keys) + unnamed_regex_group_count
                fmt_keys = get_format_string_keys(self.format)
                named_arg_count = 0
                for k in fmt_keys:
                    if k == "":
                        named_arg_count += 1
                        if named_arg_count > key_count:
                            error(
                                f"exceeded number of keys in {self.name[0]}f={self.format}")
                    elif k not in known_keys:
                        error(
                            f"unknown key {{{k}}} in {self.name[0]}f={self.format}")
            except re.error as ex:
                error(
                    f"invalid format string in {self.name[0]}f={self.format}: {str(ex)}")

    def match_xpath(self, ctx, src_xml, path, default=[], return_xml_tuple=False):
        if self.xpath is None:
            return default
        try:
            xpath_matches = src_xml.xpath(self.xpath)
        except lxml.etree.XPathEvalError as ex:
            error(f"invalid xpath: '{self.xpath}'")
        except lxml.etree.LxmlError as ex:
            error(
                f"failed to apply xpath '{self.xpath}' to {path}: "
                + f"{ex.__class__.__name__}:  {str(ex)}"
            )
        if not isinstance(xpath_matches, list):
            error(
                f"invalid xpath: '{self.xpath}'")

        if len(xpath_matches) > 1 and not self.multimatch:
            xpath_matches = xpath_matches[:1]
        res = []
        res_xml = []
        for xm in xpath_matches:
            if type(xm) == lxml.etree._ElementUnicodeResult:
                string = str(xm)
                res.append(string)
                if return_xml_tuple:
                    try:
                        res_xml.append(lxml.html.fromstring(string))
                    except lxml.LxmlError:
                        pass
            else:
                try:
                    res.append(lxml.html.tostring(xm, encoding="unicode"))
                    if return_xml_tuple:
                        res_xml.append(xm)
                except (lxml.LxmlError, UnicodeEncodeError) as ex1:
                    log(ctx, Verbosity.WARN,
                        f"{path}: xpath match encoding failed: {str(ex1)}")

        if return_xml_tuple:
            return res, res_xml
        return res

    def match_regex(self, val, path, default=[]):
        if self.regex is None or val is None:
            return default
        res = []
        for m in self.regex.finditer(val):
            res.append(RegexMatch(m.group(self.content_capture_group),
                       list(m.groups()), m.groupdict()))
            if not self.multimatch:
                break
        return res

    def apply_format(self, match, values, keys):
        if self.format is None:
            return match.value
        return self.format.format(
            *(match.group_list + [match.value] + values),
            **dict(
                [(keys[i], values[i]) for i in range(len(values))] +
                [(self.name, match.value)] + list(match.group_dict.items())
            )
        )

    def is_unset(self):
        return min([v is None for v in [self.xpath, self.regex, self.format]])

    def apply(self, ctx, src, src_xml, path, default=[], values=[], keys=[]):
        if self.is_unset():
            return default
        res = []
        for x in self.match_xpath(ctx, src_xml, path, [src]):
            for m in self.match_regex(x, path, [RegexMatch(x)]):
                res.append(self.apply_format(m, values, keys))
        return res


class Document:
    def __init__(self, document_type, path, src_mc, match_chains=None, expand_match_chains_above=None):
        self.document_type = document_type
        self.path = path
        self.encoding = None
        self.forced_encoding = False
        self.text = None
        self.xml = None
        self.src_mc = src_mc
        if not match_chains:
            self.match_chains = []
        else:
            self.match_chains = sorted(
                match_chains, key=lambda mc: mc.chain_id)
        self.expand_match_chains_above = expand_match_chains_above

    def __key(self):
        return (self.document_type, self.path)

    def __eq__(x, y):
        return isinstance(y, x.__class__) and x.__key() == y.__key()

    def __hash__(self):
        return hash(self.__key())


def obj_apply_defaults(obj, defaults, recurse_on={}):
    if obj is defaults:
        return
    for k in defaults.__dict__:
        def_val = defaults.__dict__[k]
        if k not in obj.__dict__ or obj.__dict__[k] is None:
            obj.__dict__[k] = def_val
        elif k in recurse_on:
            obj_apply_defaults(obj.__dict__[k], def_val, recurse_on)


class MatchChain:
    def __init__(self, ctx, chain_id, blank=False):
        self.cimin = 1
        self.content_escape_sequence = "<END>"

        self.cimax = float("inf")
        self.ci_continuous = False
        self.content_save_format = None
        self.content_print_format = None
        self.content_write_format = None
        self.content_raw = True
        self.content_input_encoding = "utf-8"
        self.content_forced_input_encoding = None
        self.save_path_interactive = False

        self.label_default_format = None
        self.labels_inside_content = None
        self.label_allow_missing = False
        self.allow_slashes_in_labels = False
        self.overwrite_files = True

        self.dimin = 1
        self.dimax = float("inf")
        self.default_document_encoding = "utf-8"
        self.forced_document_encoding = None

        self.default_document_scheme = ctx.fallback_document_scheme
        self.prefer_parent_document_scheme = True
        self.forced_document_scheme = None

        self.selenium_strategy = SeleniumStrategy.FIRST
        self.selenium_download_strategy = SeleniumDownloadStrategy.EXTERNAL

        if blank:
            for k in self.__dict__:
                self.__dict__[k] = None

        self.ctx = ctx
        self.chain_id = chain_id
        self.content = Locator("content", ["ci", "di", "chain"], blank)
        self.label = Locator("label", ["ci", "di", "chain"], blank)
        self.document = Locator("document", ["ci", "di", "chain"], blank)
        self.document_output_chains = [self]

        self.di = None
        self.ci = None
        self.has_xpath_matching = None
        self.has_label_matching = None
        self.has_content_xpaths = None
        self.has_document_matching = False
        self.has_content_matching = False
        self.has_interactive_matching = None
        self.content_download_required = False
        self.content_matches = []
        self.document_matches = []
        self.handled_content_matches = set()
        self.handled_document_matches = set()
        self.satisfied = True
        self.labels_none_for_n = 0

    def accepts_content_matches(self):
        return self.di <= self.dimax

    def need_document_matches(self, current_di_used):
        return (
            self.has_document_matching
            and self.di <= (self.dimax - (1 if current_di_used else 0))
        )

    def need_content_matches(self):
        return self.has_content_matching and self.ci <= self.cimax and self.di <= self.dimax

    def is_valid_label(self, label):
        if self.allow_slashes_in_labels:
            return True
        if "/" in label or "\\" in label:
            return False
        return True


class DlContext:
    def __init__(self, blank=False):
        self.cookie_file = None
        self.cookie_jar = None
        self.exit = None
        self.selenium_variant = SeleniumVariant.DISABLED
        self.tor_browser_dir = None
        self.selenium_driver = None
        self.user_agent_random = False
        self.user_agent = None
        self.verbosity = Verbosity.WARN
        self.documents_bfs = False
        self.selenium_keep_alive = False
        self.repl = False

        if blank:
            for k in self.__dict__:
                self.__dict__[k] = None

        self.cookie_dict = {}
        self.match_chains = []
        self.docs = deque()

        # stuff that can't be reconfigured (yet)
        self.selenium_timeout_secs = 10
        self.selenium_log_path = os.path.devnull
        self.selenium_poll_frequency_secs = 0.3
        self.selenium_content_count_pad_length = 6
        self.selenium_download_dir = None
        self.selenium_dl_index = 0

        self.fallback_document_scheme = "https"

        self.defaults_mc = MatchChain(self, None)
        self.origin_mc = MatchChain(self, None, blank=True)
        # turn ctx to none temporarily for origin so it can be deepcopied
        self.origin_mc.ctx = None
        self.error_code = 0


def log_raw(msg, verbosity):
    sys.stderr.write(verbosities_display_dict[verbosity] + msg + "\n")


def error(msg):
    log_raw(msg, Verbosity.ERROR)
    exit(1)


def unescape_string(txt, context):
    try:
        return txt.encode("utf-8").decode("unicode_escape")
    except (UnicodeEncodeError, UnicodeDecodeError) as ex:
        error(f"failed to unescape {context}: {str(ex)}")


def log(ctx, verbosity, msg):
    if verbosity == Verbosity.ERROR:
        ctx.error_code = 1
    if ctx.verbosity >= verbosity:
        log_raw(msg, verbosity)


def help(err=False):
    global DEFAULT_CPF
    global DEFAULT_CWF
    text = f"""{sys.argv[0]} [OPTIONS]
    Extract content from urls or files by specifying content matching chains
    (xpath -> regex -> python format string).

    Content to Write out:
        cx=<xpath>           xpath for content matching
        cr=<regex>           regex for content matching
        cf=<format string>   content format string (args: <cr capture groups>, content, di, ci)
        cm=<bool>            allow multiple content matches in one document instead of picking the first (defaults to true)
        cimin=<number>       initial content index, each successful match gets one index
        cimax=<number>       max content index, matching stops here
        cicont=<bool>        don't reset the content index for each document
        cpf=<format string>  print the result of this format string for each content, empty to disable
                             defaults to \"{DEFAULT_CPF}\" if cpf and csf are both unspecified
                             (args: content, label, encoding, document, escape, [di], [ci], [link], <lr capture groups>, <cr capture groups>)
        csf=<format string>  save content to file at the path resulting from the format string, empty to enable
                             (args: content, label, encoding, document, escape, [di], [ci], [link], <lr capture groups>, <cr capture groups>)
        owf=<bool>           allow to overwrite existing files, defaults to true
        cwf=<format string>  format to write to file. defaults to \"{DEFAULT_CWF}\"
                             (args: content, label, encoding, document, escape, [di], [ci], [link], <lr capture groups>, <cr capture groups>)
        csin<bool>           giva a promt to edit the save path for a file
        cin=<bool>           give a prompt to ignore a potential content match
        cl=<bool>            treat content match as a link to the actual content
        cesc=<string>        escape sequence to terminate content in cin mode
        cenc=<encoding>      default encoding to assume that content is in
        cfenc=<encoding>     encoding to always assume that content is in, even if http(s) says differently

    Labels to give each matched content (useful e.g. for the filename in csf):
        lx=<xpath>          xpath for label matching
        lr=<regex>          regex for label matching
        lf=<format string>  label format string (args: <lr capture groups>, label, di, ci)
        lic=<bool>          match for the label within the content match instead of the hole document
        las=<bool>          allow slashes in labels
        lm=<bool>           allow multiple label matches in one document instead of picking the first
        lam=<bool>          allow missing label (default is to skip content if no label is found)
        lfd=<format string> default label format string to use if there's no match (args: di, ci)
        lin=<bool>          give a prompt to edit the generated label

    Further documents to scan referenced in already found ones:
        dx=<xpath>          xpath for document matching
        dr=<regex>          regex for document matching
        df=<format string>  document format string (args: <dr capture groups>, document)
        dimin=<number>      initial document index, each successful match gets one index
        dimax=<number>      max document index, matching stops here
        dm=<bool>           allow multiple document matches in one document instead of picking the first
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

    Chain Syntax:
        Any option above can restrict the matching chains is should apply to using opt<chainspec>=<value>.
        Use "-" for ranges, "," for multiple specifications, and "^" to except the following chains.
        Examples:
            lf1,3-5=foo     sets "lf" to "foo" for chains 1, 3, 4 and 5.
            lf2-^4=bar      sets "lf" to "bar" for all chains larger than or equal to 2, except chain 4

    Global Options:
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
        """.strip()
    if err:
        error(text)
    else:
        print(text)


def add_cwd_to_path():
    cwd = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
    os.environ["PATH"] += ":" + cwd
    return cwd


def selenium_apply_firefox_options(ctx, ff_options):
    if ctx.user_agent is not None:
        ff_options.set_preference("general.useragent.override", ctx.user_agent)
        if ctx.selenium_variant == SeleniumVariant.TORBROWSER:
            # otherwise the user agent is not applied
            ff_options.set_preference("privacy.resistFingerprinting", False)

    prefs = {}
    # setup download dir and disable save path popup
    if ctx.selenium_download_dir is not None:
        mimetypes.init()
        save_mimetypes = ";".join(set(mimetypes.types_map.values()))
        prefs.update({
            "browser.download.dir": ctx.selenium_download_dir,
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


def setup_selenium_tor(ctx):
    # use bundled geckodriver if available
    cwd = add_cwd_to_path()
    if ctx.tor_browser_dir is None:
        tb_env_var = "TOR_BROWSER_DIR"
        if tb_env_var in os.environ:
            ctx.tor_browser_dir = os.environ[tb_env_var]
        else:
            error(f"no tbdir specified, check --help")
    try:
        options = webdriver.firefox.options.Options()
        selenium_apply_firefox_options(ctx, options)
        ctx.selenium_driver = TorBrowserDriver(
            ctx.tor_browser_dir, tbb_logfile_path=ctx.selenium_log_path, options=options)

    except WebDriverException as ex:
        error(f"failed to start tor browser: {str(ex)}")
    os.chdir(cwd)  # restore cwd that is changed by tor for some reason


def setup_selenium_firefox(ctx):
    # use bundled geckodriver if available
    add_cwd_to_path()
    options = webdriver.FirefoxOptions()
    selenium_apply_firefox_options(ctx, options)
    try:
        ctx.selenium_driver = webdriver.Firefox(
            options=options, service=selenium.webdriver.firefox.service.Service(log_path=ctx.selenium_log_path))
    except WebDriverException as ex:
        error(f"failed to start geckodriver: {str(ex)}")


def setup_selenium_chrome(ctx):
    # allow usage of bundled chromedriver
    add_cwd_to_path()
    options = webdriver.ChromeOptions()
    options.add_argument("--incognito")
    if ctx.user_agent != None:
        options.add_argument(f"user-agent={ctx.user_agent}")

    if ctx.selenium_download_dir is not None:
        prefs = {
            "download.default_directory": ctx.selenium_download_dir,
            "download.prompt_for_download": False,
            "profile.default_content_setting_values.automatic_downloads": 1,
        }
        options.add_experimental_option("prefs", prefs)

    try:
        ctx.selenium_driver = webdriver.Chrome(
            options=options, service=selenium.webdriver.chrome.service.Service(log_path=ctx.selenium_log_path))
    except WebDriverException as ex:
        error(f"failed to start chromedriver: {str(ex)}")


def selenium_add_cookies_through_get(ctx):
    # ctx.selenium_driver.set_page_load_timeout(0.01)
    for domain, cookies in ctx.cookie_dict.items():
        try:
            ctx.selenium_driver.get(f"https://{domain}")
        except selenium.common.exceptions.TimeoutException:
            error(
                "Failed to apply cookies for https://{domain}: page failed to load")
        for c in cookies.values():
            ctx.selenium_driver.add_cookie(c)


def setup_selenium(ctx):
    have_internal_dls = any(
        mc.selenium_download_strategy == SeleniumDownloadStrategy.INTERNAL
        for mc in ctx.match_chains
    )

    if have_internal_dls:
        ctx.selenium_download_dir = tempfile.mkdtemp(
            prefix="screp_selenium_downloads_")

    if ctx.selenium_variant == SeleniumVariant.TORBROWSER:
        setup_selenium_tor(ctx)
    elif ctx.selenium_variant == SeleniumVariant.CHROME:
        setup_selenium_chrome(ctx)
    elif ctx.selenium_variant == SeleniumVariant.FIREFOX:
        setup_selenium_firefox(ctx)
    else:
        assert False
    if ctx.user_agent is None:
        ctx.user_agent = ctx.selenium_driver.execute_script(
            "return navigator.userAgent;")

    ctx.selenium_driver.set_page_load_timeout(ctx.selenium_timeout_secs)
    if ctx.cookie_jar:
        # todo: implement something more clever for this, at least for chrome:
        # https://stackoverflow.com/questions/63220248/how-to-preload-cookies-before-first-request-with-python3-selenium-chrome-webdri
        selenium_add_cookies_through_get(ctx)


def get_format_string_keys(fmt_string):
    return [f for (_, f, _, _) in Formatter().parse(fmt_string) if f is not None]


def format_string_uses_arg(fmt_string, arg_pos, arg_name):
    if fmt_string is None:
        return False
    fmt_args = get_format_string_keys(fmt_string)
    if arg_name is not None and arg_name in fmt_args:
        return True
    if arg_pos is not None and fmt_args.count("") > arg_pos:
        return True
    return False


def setup_match_chain(mc, ctx):
    # we need ctx because mc.ctx is stil None before we apply_defaults
    obj_apply_defaults(mc, ctx.defaults_mc, {
                       "content": {}, "label": {}, "document": {}})
    locators = [mc.content, mc.label, mc.document]
    for l in locators:
        l.setup()

    if ctx.selenium_variant == SeleniumVariant.TORBROWSER:
        if mc.selenium_download_strategy == SeleniumDownloadStrategy.EXTERNAL:
            mc.selenium_download_variant = SeleniumDownloadStrategy.FETCH
            log(ctx, Verbosity.WARN,
                f"match chain {mc.chain_id}: switching to 'fetch' download strategy since 'external' is incompatible with sel=tor")

    if mc.dimin > mc.dimax:
        error(f"dimin can't exceed dimax")
    if mc.cimin > mc.cimax:
        error(f"cimin can't exceed cimax")
    mc.ci = mc.cimin
    mc.di = mc.dimin

    if mc.content_write_format and not mc.content_save_format:
        log(ctx, Verbosity.ERROR,
            f"match chain {mc.chain_id}: cannot specify cwf without csf")
        raise ValueError()

    if mc.save_path_interactive and not mc.content_save_format:
        mc.content_save_format = ""

    if not mc.content_write_format:
        mc.content_write_format = DEFAULT_CWF

    if not mc.content_print_format and not mc.content_save_format:
        mc.content_print_format = DEFAULT_CPF

    if mc.content_print_format:
        mc.content_print_format = unescape_string(
            mc.content_print_format, "cpf")
    if mc.content_save_format:
        mc.content_save_format = unescape_string(mc.content_save_format, "csf")
        mc.content_write_format = unescape_string(
            mc.content_write_format, "cwf")

    mc.has_xpath_matching = any(l.xpath is not None for l in locators)
    mc.has_label_matching = mc.label.xpath is not None or mc.label.regex is not None
    mc.has_content_xpaths = mc.labels_inside_content is not None and mc.label.xpath is not None
    mc.has_document_matching = mc.has_document_matching or mc.document.xpath is not None or mc.document.regex is not None or mc.document.format is not None
    mc.has_content_matching = mc.has_content_matching or mc.content.xpath is not None or mc.content.regex is not None or mc.content.format is not None
    mc.has_interactive_matching = mc.label.interactive or mc.content.interactive

    if not mc.has_label_matching:
        mc.label_allow_missing = True
        if mc.labels_inside_content:
            log(ctx, Verbosity.ERROR,
                f"match chain {mc.chain_id}: cannot specify lic without lx or lr")
            raise ValueError()

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
    if not mc.content_raw:
        output_formats = [
            mc.content_save_format,
            mc.content_write_format,
            mc.content_print_format
        ]
        mc.content_download_required = any(
            format_string_uses_arg(of, None, "content") for of in output_formats
        )

    if not mc.has_content_matching and not mc.has_document_matching:
        if any(mc in doc.match_chains for doc in mc.ctx.docs):
            log(ctx, Verbosity.ERROR,
                f"match chain {mc.chain_id} is unused, it has neither document nor content matching")
            raise ValueError()


def load_cookie_jar(ctx):
    try:
        ctx.cookie_jar = MozillaCookieJar()
        ctx.cookie_jar.load(
            os.path.expanduser(ctx.cookie_file),
            ignore_discard=True, ignore_expires=True)
    # this exception handling is really ugly but this is how this library
    # does it internally
    except OSError:
        raise
    except Exception as ex:
        error(f"failed to read cookie file: {str(ex)}")
    for cookie in ctx.cookie_jar:
        ck = {
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
        ctx.cookie_list.append(ck)


def setup(ctx):
    global DEFAULT_CPF
    if len(ctx.docs) == 0 and not ctx.repl:
        log(ctx, Verbosity.ERROR, "must specify at least one url or (r)file")
        raise ValueError()
    obj_apply_defaults(ctx, DlContext(blank=False))

    if ctx.tor_browser_dir:
        if ctx.selenium_variant == SeleniumVariant.DISABLED:
            ctx.selenium_variant = SeleniumVariant.TORBROWSER
    if ctx.cookie_file is not None:
        load_cookie_jar(ctx)

    if ctx.user_agent is not None and ctx.user_agent_random:
        log(ctx, Verbosity.ERROR, f"the options ua and uar are incompatible")
        raise ValueError()
    elif ctx.user_agent_random:
        user_agent_rotator = UserAgent()
        ctx.user_agent = user_agent_rotator.get_random_user_agent()
    elif ctx.user_agent is None and ctx.selenium_variant == SeleniumVariant.DISABLED:
        ctx.user_agent = "screp/0.2.0"

    # if no chains are specified, use the origin chain as chain 0
    chain_zero_enabled = True in (
        d.match_chains[0:1] == ctx.match_chains[0:1] for d in ctx.docs)
    if not ctx.match_chains:
        ctx.match_chains = [ctx.origin_mc]
        ctx.origin_mc.chain_id = 0
        chain_zero_enabled = True

    for d in ctx.docs:
        if d.expand_match_chains_above is not None:
            if not chain_zero_enabled and d.expand_match_chains_above == 0:
                d.expand_match_chains_above = 1
            d.match_chains.extend(
                ctx.match_chains[d.expand_match_chains_above:])

    # the default strategy changes if we are using tor
    if ctx.selenium_variant == SeleniumVariant.TORBROWSER:
        ctx.defaults_mc.selenium_download_strategy = SeleniumDownloadStrategy.FETCH

    for mc in ctx.match_chains:
        setup_match_chain(mc, ctx)

    if ctx.selenium_variant == SeleniumVariant.DISABLED:
        for mc in ctx.match_chains:
            mc.selenium_strategy = SeleniumStrategy.DISABLED
        return

    # reuse selenium in repl mode
    if ctx.selenium_driver is None:
        setup_selenium(ctx)


def parse_prompt_option(val, options, default=None, unparsable_val=None):
    val = val.strip().lower()
    if val == "":
        return default
    for opt, matchings in options:
        if val in matchings:
            return opt
    return unparsable_val


def parse_bool_string(val, default=None, unparsable_val=None):
    return parse_prompt_option(val, [(True, yes_indicating_strings), (False, no_indicating_strings)], default, None)


def prompt(prompt_text, options, default=None):
    assert len(options) > 1
    while True:
        res = parse_prompt_option(input(prompt_text), options, default)
        if res is None:
            option_names = [matchings[0] for _opt, matchings in options]
            print("please answer with " +
                  ", ".join(option_names[:-1]) + " or " + option_names[-1])
            continue
        return res


def prompt_yes_no(prompt_text, default=None):
    return prompt(prompt_text, [(True, yes_indicating_strings), (False, no_indicating_strings)], default)


def selenium_has_died(ctx):
    try:
        # throws an exception if the session died
        return not len(ctx.selenium_driver.window_handles) > 0
    except WebDriverException as e:
        return True


def selenium_download_from_local_file(mc, di_ci_context, doc, doc_url, link, filepath):
    if not os.path.isabs(link):
        cur_path = os.path.realpath(os.path.dirname(doc_url[len("file:"):]))
        filepath = os.path.join(cur_path, link)
    with open(filepath, "rb") as f:
        return f.read()


def selenium_download_external(mc, di_ci_context, doc, doc_url, link, filepath):
    # we absolutely don't want to use this for tor since it would
    # expose our real ip to the server
    assert mc.ctx.selenium_variant != SeleniumVariant.TORBROWSER
    try:
        res = requests_dl(mc.ctx, link, mc.ctx.selenium_driver.get_cookies())
        data = res.content
        res.close()
        return data
    except requests.exceptions.ConnectionError:
        log(mc.ctx, Verbosity.ERROR,
            f"{doc.path}{di_ci_context}: failed to download '{link}': connection failed")
        return None


def selenium_setup_cors_tab(ctx, doc_link, link, dl_index):
    doc_url = urllib.parse.urlparse(doc_link)
    link_url = urllib.parse.urlparse(link)
    if doc_url.netloc == link_url.netloc:
        return None
    prev_window_handle = ctx.selenium_driver.current_window_handle
    host_link = link_url._replace(
        path="", params="", query="", fragment="").geturl()
    cors_tab = f"screp_cors_tab_{dl_index}"
    ctx.selenium_driver.execute_script(
        "window.open('about:blank', arguments[0]);",
        cors_tab
    )
    ctx.selenium_driver.switch_to.window(cors_tab)
    ctx.selenium_driver.get(host_link)
    return prev_window_handle


def selenium_close_cors_tab(ctx, cors_prev_tab):
    if cors_prev_tab is not None:
        ctx.selenium_driver.close()
        ctx.selenium_driver.switch_to.window(cors_prev_tab)


def selenium_download_internal(mc, di_ci_context, doc, doc_url, link, filepath=None):
    dl_index = mc.ctx.selenium_dl_index
    mc.ctx.selenium_dl_index += 1
    tmp_filename = f"dl{dl_index}"
    if filepath is not None:
        tmp_filename += "_" + os.path.basename(filepath)
    else:
        tmp_filename += ".bin"

    tmp_path = os.path.join(mc.ctx.selenium_download_dir, tmp_filename)

    link_url = urllib.parse.urlparse(link)
    doc_url = urllib.parse.urlparse(doc_url)
    if doc_url.netloc != link_url.netloc:
        log(mc.ctx, Verbosity.ERROR,
            f"{link}{di_ci_context}: failed to download: seldl=internal does not work across origins")
        return None

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
        mc.ctx.selenium_driver.execute_script(
            script_source, link, tmp_filename)
    except WebDriverException as ex:
        if selenium_has_died(mc.ctx):
            warn_selenium_died(mc.ctx)
        else:
            log(mc.ctx, Verbosity.ERROR,
                f"{link}{di_ci_context}: selenium download failed: {str(ex)}")
        return None
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
                if selenium_has_died(mc.ctx):
                    return None

        i += 1
    with open(tmp_path, "rb") as f:
        data = f.read()
    os.remove(tmp_path)
    return data


def selenium_download_fetch(mc, di_ci_context, doc, doc_url, link, filepath=None):
    dl_index = mc.ctx.selenium_dl_index
    mc.ctx.selenium_dl_index += 1
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
    try:
        res = mc.ctx.selenium_driver.execute_script(
            script_source, link)
    except WebDriverException as ex:
        if selenium_has_died(mc.ctx):
            warn_selenium_died(mc.ctx)
            return None
        err = str(ex)
    if "error" in res:
        err = res["error"]
    if err is not None:
        cors_warn = ""
        if urllib.parse.urlparse(doc_url).netloc != urllib.parse.urlparse(link).netloc:
            cors_warn = " (potential CORS issue)"
        log(mc.ctx, Verbosity.ERROR,
            f"{doc.path}{di_ci_context}: selenium download of '{link}' failed{cors_warn}: {err}")
        return None
    return binascii.a2b_base64(res["ok"])


def selenium_download(mc, doc, di_ci_context, link, filepath=None):
    doc_url = mc.ctx.selenium_driver.current_url

    if doc.document_type == DocumentType.FILE and urllib.parse.urlparse(link).scheme in ["", "file"]:
        return selenium_download_from_local_file(mc, di_ci_context, doc, doc_url, link, filepath)

    if mc.selenium_download_strategy == SeleniumDownloadStrategy.EXTERNAL:
        return selenium_download_external(mc, di_ci_context, doc, doc_url, link, filepath)

    if mc.selenium_download_strategy == SeleniumDownloadStrategy.INTERNAL:
        return selenium_download_internal(mc, di_ci_context, doc, doc_url, link, filepath)

    assert mc.selenium_download_strategy == SeleniumDownloadStrategy.FETCH

    return selenium_download_fetch(mc, di_ci_context, doc, doc_url, link, filepath)


def requests_dl(ctx, path, cookie_dict=None):
    hostname = urllib.parse.urlparse(path).hostname
    if cookie_dict is None:
        cookie_dict = ctx.cookie_dict.get(hostname, {})
    cookies = {
        name: ck["value"]
        for name, ck in cookie_dict
        if ck.get("domain", hostname) == hostname
    }
    headers = {'User-Agent': ctx.user_agent}
    return requests.get(
        path, cookies=cookies, headers=headers, allow_redirects=True
    )


def warn_selenium_died(ctx):
    log(ctx, Verbosity.WARN, "the selenium instance was closed unexpectedly")


def report_selenium_error(ctx, ex):
    log(ctx, Verbosity.ERROR, f"critical selenium error: {str(ex)}")


def download_content(mc, doc, di_ci_context, content_match, di, ci, label, content, content_path, save_path):
    if not mc.content_raw:
        if mc.content_download_required:
            if mc.ctx.selenium_variant != SeleniumVariant.DISABLED:
                content = selenium_download(
                    mc, doc, di_ci_context, content_path, save_path)
                if content is None:
                    return InteractiveResult.ACCEPT
            else:
                if doc.document_type.derived_type() is DocumentType.FILE:
                    with open(content_path, "rb") as f:
                        content = f.read()
                else:
                    res = requests_dl(mc.ctx, content_path)
                    content = res.content
                    res.close()

    if mc.content_print_format:
        print_data = gen_final_content_format(
            mc, mc.content_print_format, label, di, ci, content_path,
            content, content_match.label_regex_match, content_match.content_regex_match,
            doc
        )
        sys.stdout.buffer.write(print_data)
        sys.stdout.flush()

    if save_path:
        try:
            f = open(save_path, ("w" if mc.overwrite_files else "x") + "b")
        except FileExistsError:
            log(mc.ctx, Verbosity.ERROR,
                f"{doc.path}{di_ci_context}: file already exists: {save_path}")
            return InteractiveResult.ACCEPT
        except OSError as ex:
            log(mc.ctx, Verbosity.ERROR,
                f"{doc.path}{di_ci_context}: failed to write to file '{save_path}': {ex.msg}")
            return InteractiveResult.ACCEPT

        write_data = gen_final_content_format(
            mc, mc.content_write_format, label, di, ci, content_path,
            content, content_match.label_regex_match, content_match.content_regex_match,
            doc
        )
        f.write(write_data)
        f.close()
        log(mc.ctx, Verbosity.INFO,
            f"{doc.path}{di_ci_context}: wrote content into {save_path}")


class ScrepFetchError(Exception):
    pass


def fetch_doc(ctx, doc):
    if ctx.selenium_variant != SeleniumVariant.DISABLED:
        selpath = doc.path
        if doc.document_type in [DocumentType.FILE, DocumentType.RFILE]:
            selpath = "file:" + os.path.realpath(selpath)
        ctx.selenium_driver.get(selpath)
        decide_document_encoding(ctx, doc)
        doc.text = ctx.selenium_driver.page_source
        return
    if doc.document_type in [DocumentType.FILE, DocumentType.RFILE]:
        try:
            with open(doc.path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            raise ScrepFetchError("no such file or directory")
        decide_document_encoding(ctx, doc)
        doc.text = data.decode(doc.encoding, errors="surrogateescape")
        return
    assert doc.document_type == DocumentType.URL
    res = requests_dl(ctx, doc.path)
    data = res.content
    res.close()
    if data is None:
        raise ScrepFetchError("empty response")
    doc.encoding = res.encoding
    decide_document_encoding(ctx, doc)
    doc.text = data.decode(doc.encoding, errors="surrogateescape")
    return


def gen_final_content_format(mc, format_str, label, di, ci, content_link, content, label_regex_match, content_regex_match, doc):
    opts_list = []
    opts_dict = {}
    if mc.document.multimatch:
        opts_list.append(di)
        opts_dict["di"] = di
    if mc.content.multimatch:
        opts_list.append(ci)
        opts_dict["ci"] = ci
    if content_link is not None:
        opts_list.append(content_link)
        opts_dict["link"] = content_link
    if content is not None:
        opts_dict["content"] = content

    if label_regex_match is None:
        label_regex_match = RegexMatch(None)
    if content_regex_match is None:
        content_regex_match = RegexMatch(None)

    args_list = label_regex_match.group_list + content_regex_match.group_list
    args_dict = dict(
        list(content_regex_match.group_dict.items())
        + list(label_regex_match.group_dict.items())
        + list(opts_dict.items())
        + list(
            {
                "label": label,
                "encoding": doc.encoding,
                "document": doc.path,
                "escape": mc.content_escape_sequence
            }.items()
        )
    )
    res = b''
    args_list.reverse()
    for (text, key, format_args, b) in Formatter().parse(format_str):
        if text is not None:
            res += text.encode("utf-8")
        if key is not None:
            if key == "":
                val = args_list.pop()
            else:
                val = args_dict[key]
            if type(val) is bytes:
                res += val
            else:
                res += format(val, format_args).encode("utf-8",
                                                       errors="surrogateescape")
    return res


def normalize_link(ctx, mc, src_doc, doc_path, link):
    # todo: make this configurable
    if src_doc.document_type == DocumentType.FILE:
        return link
    url_parsed = urllib.parse.urlparse(link)
    doc_url_parsed = urllib.parse.urlparse(doc_path) if doc_path else None

    if doc_url_parsed and url_parsed.netloc == "" and src_doc.document_type == DocumentType.URL:
        url_parsed = url_parsed._replace(netloc=doc_url_parsed.netloc)

    # for urls like 'google.com' urllib makes this a path instead of a netloc
    if url_parsed.netloc == "" and not doc_url_parsed and url_parsed.scheme == "" and url_parsed.path != "" and link[0] not in [".", "/"]:
        url_parsed = url_parsed._replace(path="", netloc=url_parsed.path)
    if (mc and mc.forced_document_scheme):
        url_parsed = url_parsed._replace(scheme=mc.forced_document_scheme)
    elif url_parsed.scheme == "":
        if (mc and mc.prefer_parent_document_scheme) and doc_url_parsed and doc_url_parsed.scheme not in ["", "file"]:
            scheme = doc_url_parsed.scheme
        elif mc and mc.default_document_scheme:
            scheme = mc.default_document_scheme
        else:
            scheme = ctx.fallback_document_scheme
        url_parsed = url_parsed._replace(scheme=scheme)
    res = url_parsed.geturl()
    return res


def handle_content_match(mc, doc, content_match):
    ci = mc.ci
    di = mc.di
    label_regex_match = content_match.label_regex_match
    content = mc.content.apply_format(
        content_match.content_regex_match,
        [di, ci],
        ["di", "ci"],
    )

    if label_regex_match is None:
        label = mc.label_default_format.format([di, ci], di=di, ci=ci)
    else:
        label = mc.label.apply_format(
            label_regex_match, [di, ci], ["di", "ci"])

    di_ci_context = ""
    if mc.has_document_matching:
        if mc.content.multimatch:
            di_ci_context = f" (di={di}, ci={ci})"
        else:
            di_ci_context = f" (di={di})"
    elif mc.content.multimatch:
        di_ci_context = f" (ci={ci})"

    if mc.has_label_matching:
        label_context = f' (label "{label}")'
    else:
        label_context = ""

    content_link = None if mc.content_raw else content

    while True:
        if not mc.content_raw:
            if mc.ctx.selenium_variant == SeleniumVariant.DISABLED:
                doc_url = doc.path
            else:
                try:
                    doc_url = mc.ctx.selenium_driver.current_url
                except WebDriverException as ex:
                    # selenium died, abort
                    if selenium_has_died(mc.ctx):
                        warn_selenium_died(mc.ctx)
                    else:
                        report_selenium_error(mc.ctx, ex)
                    return InteractiveResult.REJECT

            content_link = normalize_link(
                mc.ctx, mc, doc, doc_url, content_link)

        if mc.content.interactive:
            prompt_options = [
                (InteractiveResult.ACCEPT, yes_indicating_strings),
                (InteractiveResult.REJECT, no_indicating_strings),
                (InteractiveResult.EDIT, edit_indicating_strings),
                (InteractiveResult.SKIP_CHAIN, chain_skip_indicating_strings),
                (InteractiveResult.SKIP_DOC, doc_skip_indicating_strings)
            ]
            if mc.content_raw:
                prompt_options.append(
                    (InteractiveResult.INSPECT, inspect_indicating_strings))
                inspect_opt_str = "/inspect"
                prompt_msg = f'accept content from "{doc.path}"{di_ci_context}{label_context}'
            else:
                inspect_opt_str = ""
                prompt_msg = f'"{doc.path}"{di_ci_context}{label_context} accept content link "{content_link}"'

            res = prompt(
                f'{prompt_msg} [Yes/no/edit{inspect_opt_str}/chainskip/docskip]? ',
                prompt_options,
                InteractiveResult.ACCEPT
            )
            if res is InteractiveResult.ACCEPT:
                break
            if res == InteractiveResult.INSPECT:
                print(
                    f'content for "{doc.path}"{label_context}:\n' + content)
                continue
            if res is not InteractiveResult.EDIT:
                return res
            if not mc.content_raw:
                content_link = input("enter new content link:\n")
            else:
                print(
                    f'enter new content (terminate with a newline followed by the string "{mc.content_escape_sequence}"):\n')
                content = ""
                while True:
                    content += input() + "\n"
                    i = content.find("\n" + mc.content_escape_sequence)
                    if i != -1:
                        content = content[:i]
                        break
        break

    if mc.label.interactive:
        while True:
            if not mc.is_valid_label(label):
                log(mc.ctx, Verbosity.WARN,
                    f'"{doc.path}": labels cannot contain a slash ("{label}")')
            else:
                prompt_options = [
                    (InteractiveResult.ACCEPT, yes_indicating_strings),
                    (InteractiveResult.REJECT, no_indicating_strings),
                    (InteractiveResult.EDIT, edit_indicating_strings),
                    (InteractiveResult.SKIP_CHAIN, chain_skip_indicating_strings),
                    (InteractiveResult.SKIP_DOC, doc_skip_indicating_strings)
                ]
                if mc.content_raw:
                    prompt_options.append(
                        (InteractiveResult.INSPECT, inspect_indicating_strings))
                    inspect_opt_str = "/inspect"
                    prompt_msg = f'"{doc.path}"{di_ci_context}: accept content label "{label}"'
                else:
                    inspect_opt_str = ""
                    prompt_msg = f'"{doc.path}": content link {content_link}{di_ci_context}: accept content label "{label}"'

                res = prompt(
                    f'{prompt_msg} [Yes/no/edit/{inspect_opt_str}/chainskip/docskip]? ',
                    prompt_options,
                    InteractiveResult.ACCEPT
                )
                if res == InteractiveResult.ACCEPT:
                    break
                if res == InteractiveResult.INSPECT:
                    print(f'"{doc.path}": content for "{label}":\n' + content)
                    continue
                if res != InteractiveResult.EDIT:
                    return res
            label = input("enter new label: ")

    save_path = None
    if mc.content_save_format:
        if not mc.is_valid_label(label):
            log(mc.ctx, Verbosity.WARN,
                f"matched label '{label}' would contain a slash, skipping this content from: {doc.path}")
        save_path = gen_final_content_format(
            mc, mc.content_save_format, label, di, ci, content_link,
            content, content_match.label_regex_match, content_match.content_regex_match,
            doc
        )
        try:
            save_path = save_path.decode("utf-8", errors="surrogateescape")
        except UnicodeDecodeError:
            log(mc.ctx, Verbosity.ERROR,
                f"{doc.path}{di_ci_context}: generated save path is not valid utf-8")
            save_path = None
        while True:
            if save_path and not os.path.exists(os.path.dirname(os.path.abspath(save_path))):
                log(mc.ctx, Verbosity.ERROR,
                    f"{doc.path}{di_ci_context}: directory of generated save path does not exist")
                save_path = None
            if not save_path and not mc.save_path_interactive:
                return False
            if not mc.save_path_interactive:
                break
            if save_path:
                res = prompt(
                    f'{doc.path}{di_ci_context}: accept save path "{save_path}" [Yes/no/edit/chainskip/docskip]? ',
                    [
                        (InteractiveResult.ACCEPT, yes_indicating_strings),
                        (InteractiveResult.REJECT, no_indicating_strings),
                        (InteractiveResult.EDIT, edit_indicating_strings),
                        (InteractiveResult.SKIP_CHAIN,
                         chain_skip_indicating_strings),
                        (InteractiveResult.SKIP_DOC, doc_skip_indicating_strings)
                    ],
                    InteractiveResult.ACCEPT
                )
                if res == InteractiveResult.ACCEPT:
                    break
                if res != InteractiveResult.EDIT:
                    return res
            save_path = input("enter new save path: ")

    download_content(mc, doc, di_ci_context, content_match, di,
                     ci, label, content, content_link, save_path)

    mc.ci += 1
    return InteractiveResult.ACCEPT


def handle_document_match(ctx, doc):
    if not ctx.document.interactive:
        return InteractiveResult.ACCEPT
    while True:
        res = prompt(
            f'accept matched document "{doc.path}" [Yes/no/edit]? ',
            [
                (InteractiveResult.ACCEPT, yes_indicating_strings),
                (InteractiveResult.REJECT, no_indicating_strings),
                (InteractiveResult.EDIT, edit_indicating_strings),
                (InteractiveResult.SKIP_CHAIN, chain_skip_indicating_strings),
                (InteractiveResult.SKIP_DOC, doc_skip_indicating_strings)
            ],
            InteractiveResult.ACCEPT
        )
        if res == InteractiveResult.EDIT:
            doc.path = input("enter new document: ")
            continue
        return res


def gen_content_matches(mc, doc):
    content_matches = []

    if mc.has_content_xpaths:
        contents, contents_xml = mc.content.match_xpath(
            mc.ctx, doc.xml, doc.path, ([doc.src], [doc.xml]), True)
    else:
        contents = mc.content.match_xpath(
            mc.ctx, doc.xml, doc.path, [doc.text]
        )

    labels = []
    if mc.has_label_matching and not mc.labels_inside_content:
        for lx in mc.label.match_xpath(mc.ctx, doc.xml, doc.path, [doc.text]):
            labels.extend(mc.label.match_regex(
                doc.text, doc.path, [RegexMatch(lx)])
            )
    match_index = 0
    labels_none_for_n = 0
    for content in contents:
        content_regex_matches = mc.content.match_regex(
            content, doc.path, [RegexMatch(content)])
        if mc.labels_inside_content and mc.label.xpath:
            content_xml = contents_xml[match_index] if mc.has_content_xpaths else None
            labels = []
            for lx in mc.label.match_xpath(mc.ctx, content_xml, doc.path, [doc.text]):
                labels.extend(mc.label.match_regex(
                    doc.text, doc.path, [RegexMatch(lx)]))
            if len(labels) == 0:
                if not mc.label_allow_missing:
                    labels_none_for_n += len(content_regex_matches)
                    continue
                label = None
            else:
                label = labels[0]

        for crm in content_regex_matches:
            if mc.labels_inside_content:
                if not mc.label.xpath:
                    labels = mc.label.match_regex(
                        crm.value, doc.path, [RegexMatch(crm.value)])
                    if len(labels) == 0:
                        if not mc.label_allow_missing:
                            labels_none_for_n += 1
                            continue
                        label = None
                    else:
                        label = labels[0]
            else:
                if not mc.label.multimatch and len(labels) > 0:
                    label = labels[0]
                elif match_index < len(labels):
                    label = labels[match_index]
                elif not mc.label_allow_missing:
                    labels_none_for_n += 1
                    continue
                else:
                    label = None

            content_matches.append(ContentMatch(label, crm))
        match_index += 1
    return content_matches, labels_none_for_n


def gen_document_matches(mc, doc):
    # TODO: fix interactive matching for docs and give ci di chain to regex
    paths = mc.document.apply(mc.ctx, doc.text, doc.xml, doc.path)
    if doc.document_type == DocumentType.FILE:
        base = os.path.dirname(doc.path)
        for i, p in enumerate(paths):
            if not os.path.isabs(p):
                paths[i] = os.path.normpath(os.path.join(base, p))
    return [
        Document(
            doc.document_type.derived_type(),
            path,
            mc,
            mc.document_output_chains
        )
        for path in paths
    ]


def make_padding(ctx, count_number):
    content_count_pad_len = (
        ctx.selenium_content_count_pad_length
        - min(len(str(count_number)), ctx.selenium_content_count_pad_length)
    )
    rpad = int(content_count_pad_len / 2)
    lpad = content_count_pad_len - rpad
    return lpad * " ", rpad * " "


def handle_interactive_chains(ctx, interactive_chains, doc, try_number, last_msg):
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

    msg = f'"{doc.path}": use page with potentially'
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

    rlist = []
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
            [(InteractiveResult.ACCEPT, yes_indicating_strings),
             (InteractiveResult.SKIP_DOC, skip_indicating_strings + no_indicating_strings)],
            InteractiveResult.ACCEPT
        )
        if result is None:
            print('please answer with "yes" or "skip"')
            sys.stdout.write(msg)
            sys.stdout.flush()
    if result:
        return result, msg
    else:
        return result, msg


def handle_match_chain(mc, doc):
    if mc.need_content_matches():
        content_matches, mc.labels_none_for_n = gen_content_matches(
            mc, doc)
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
            cm.handled_document_matches.add(dm)
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
            SeleniumStrategy.INTERACTIVE, SeleniumStrategy.DEDUP]
        interactive = True

    return waiting, interactive


def accept_for_match_chain(mc, doc, content_skip_doc, documents_skip_doc):
    if not mc.ci_continuous:
        mc.ci = mc.cimin
    if not content_skip_doc:
        for i, cm in enumerate(mc.content_matches):
            if not mc.has_label_matching or cm.label_regex_match is not None:
                if mc.ci > mc.cimax:
                    break
                res = handle_content_match(mc, doc, cm)
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
        accepted_document_matches = []
        for d in mc.document_matches:
            res = handle_document_match(mc, d)
            if res == InteractiveResult.SKIP_CHAIN:
                break
            if res == InteractiveResult.SKIP_DOC:
                documents_skip_doc = True
                break
            if res == InteractiveResult.ACCEPT:
                accepted_document_matches.append(d)

        if mc.ctx.documents_bfs:
            mc.ctx.docs.extend(accepted_document_matches)
        else:
            mc.ctx.docs.extendleft(accepted_document_matches)
    mc.document_matches.clear()
    mc.content_matches.clear()
    mc.handled_document_matches.clear()
    mc.handled_content_matches.clear()
    mc.di += 1
    return content_skip_doc, documents_skip_doc


def decide_document_encoding(ctx, doc):
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


def parse_xml(ctx, doc, src, enc, forced_enc):
    try:
        src_bytes = src.encode(enc, errors="surrogateescape")
        if src.strip() == "":
            src_xml = lxml.etree.Element("html")
        elif forced_enc:
            src_xml = lxml.html.fromstring(
                src_bytes,
                parser=lxml.html.HTMLParser(encoding=enc)
            )
        else:
            src_xml = lxml.html.fromstring(src_bytes)
        return src_xml
    except (lxml.LxmlError, UnicodeEncodeError, UnicodeDecodeError) as ex:
        log(ctx, Verbosity.ERROR,
            f"{doc.path}: failed to parse as xml: {str(ex)}")
        return None


def dl(ctx, reused_doc=None):
    closed = False
    doc = None
    while ctx.docs:
        doc = ctx.docs.popleft()
        unsatisfied_chains = 0
        have_xpath_matching = 0
        for mc in doc.match_chains:
            if mc.need_document_matches(False) or mc.need_content_matches():
                unsatisfied_chains += 1
                mc.satisfied = False
                if mc.has_xpath_matching:
                    have_xpath_matching += 1

        try_number = 0
        try:
            if doc is not reused_doc:
                fetch_doc(ctx, doc)
        except WebDriverException as ex:
            if selenium_has_died(ctx):
                warn_selenium_died(ctx)
            else:
                log(ctx, Verbosity.ERROR,
                    f"Failed to fetch {doc.path}: {str(ex)}")
            break
        except ScrepFetchError as ex:
            log(ctx, Verbosity.ERROR, f"Failed to fetch {doc.path}: {str(ex)}")
            continue
        except requests.exceptions.ConnectionError as ex:
            log(ctx, Verbosity.ERROR,
                f"Failed to fetch {doc.path}: connection failed")
            continue
        static_content = (
            doc.document_type != DocumentType.URL or ctx.selenium_variant == SeleniumVariant.DISABLED)
        last_msg = ""
        while unsatisfied_chains > 0:
            try_number += 1
            same_content = static_content and try_number > 1
            if try_number > 1 and not static_content:
                assert ctx.selenium_variant != SeleniumVariant.DISABLED
                try:
                    src_new = ctx.selenium_driver.page_source
                    same_content = (src_new == doc.text)
                    doc.text = src_new
                except WebDriverException as e:
                    if selenium_has_died(ctx):
                        warn_selenium_died(ctx)
                    else:
                        log(ctx, Verbosity.ERROR,
                            f"selenium failed to fetch page source: {str(ex)}")
                    break

            if not same_content:
                interactive_chains = []
                if have_xpath_matching:
                    doc.xml = parse_xml(
                        ctx, doc, doc.text,
                        doc.encoding, doc.forced_encoding
                    )
                    if doc.xml is None:
                        break

                for mc in doc.match_chains:
                    if mc.satisfied:
                        continue
                    waiting, interactive = handle_match_chain(mc, doc)
                    if not waiting:
                        mc.satisfied = True
                        unsatisfied_chains -= 1
                        if mc.has_xpath_matching:
                            have_xpath_matching -= 1
                    elif interactive:
                        interactive_chains.append(mc)

            if interactive_chains:
                accept, last_msg = handle_interactive_chains(
                    ctx, interactive_chains, doc, try_number, last_msg)
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
        content_skip_doc, doc_skip_doc = False, False
        for mc in doc.match_chains:
            if not mc.satisfied:
                # ignore skipped chains
                continue
            content_skip_doc, doc_skip_doc = accept_for_match_chain(
                mc, doc, content_skip_doc, doc_skip_doc
            )
    return doc


def finalize(ctx):
    if not ctx.selenium_keep_alive:
        if ctx.selenium_variant != SeleniumVariant.DISABLED and not selenium_has_died(ctx):
            try:
                ctx.selenium_driver.close()
            except WebDriverException:
                pass
    if ctx.selenium_download_dir:
        shutil.rmtree(ctx.selenium_download_dir)


def begins(string, begin):
    return len(string) >= len(begin) and string[0:len(begin)] == begin


def parse_mc_range_int(ctx, v, arg):
    try:
        return int(v)
    except ValueError:
        error(
            f"failed to parse '{v}' as an integer for match chain specification of '{arg}'")


def extend_match_chain_list(ctx, needed_id):
    if len(ctx.match_chains) > needed_id:
        return
    for i in range(len(ctx.match_chains), needed_id+1):
        mc = copy.deepcopy(ctx.origin_mc)
        mc.chain_id = i
        ctx.match_chains.append(mc)


def parse_simple_mc_range(ctx, mc_spec, arg):
    sections = mc_spec.split(",")
    ranges = []
    for s in sections:
        s = s.strip()
        if s == "":
            error(
                "invalid empty range in match chain specification of '{arg}'")
        dash_split = [r.strip() for r in s.split("-")]
        if len(dash_split) > 2 or s == "-":
            error(
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
                    error(
                        f"second value must be larger than first for range {s} in match chain specification of '{arg}'")
                extend_match_chain_list(ctx, snd)
            ranges.append(ctx.match_chains[fst: snd + 1])
    return itertools.chain(*ranges)


def parse_mc_range(ctx, mc_spec, arg):
    if mc_spec == "":
        return [ctx.defaults_mc]

    esc_split = [x.strip() for x in mc_spec.split("^")]
    if len(esc_split) > 2:
        error(
            f"cannot have more than one '^' in match chain specification of '{arg}'")
    if len(esc_split) == 1:
        return parse_simple_mc_range(ctx, mc_spec, arg)
    lhs, rhs = esc_split
    if lhs == "":
        exclude = parse_simple_mc_range(ctx, rhs, arg)
        include = itertools.chain(ctx.match_chains, [ctx.origin_mc])
    else:
        exclude = parse_simple_mc_range(ctx, rhs, arg)
        chain_count = len(ctx.match_chains)
        include = parse_simple_mc_range(ctx, lhs, arg)
        # hack: parse exclude again so the newly generated chains form include are respected
        if chain_count != len(ctx.match_chains):
            exclude = parse_simple_mc_range(ctx, rhs, arg)
    return ({*include} - {*exclude})


def parse_mc_arg(ctx, argname, arg, support_blank=False, blank_value=""):
    if not begins(arg, argname):
        return False, None, None
    argname_len = len(argname)
    eq_pos = arg.find("=")
    if eq_pos == -1:
        if arg != argname:
            return False, None, None
        if not support_blank:
            error("missing equals sign in argument '{arg}'")
        pre_eq_arg = arg
        value = blank_value
        mc_spec = arg[argname_len:]
    else:
        mc_spec = arg[argname_len: eq_pos]
        if not chain_regex.match(mc_spec):
            return False, None, None
        pre_eq_arg = arg[:eq_pos]
        value = arg[eq_pos+1:]
    return True, parse_mc_range(ctx, mc_spec, pre_eq_arg), value


def follow_attribute_path_spec(obj, spec):
    for s in spec:
        obj = obj.__dict__[s]
    return obj


def parse_mc_range_as_arg(ctx, argname, argval):
    return list(parse_mc_range(ctx, argval, argname))


def apply_mc_arg(ctx, argname, config_opt_names, arg, value_cast=lambda x, _arg: x, support_blank=False, blank_value=""):
    success, mcs, value = parse_mc_arg(
        ctx, argname, arg, support_blank, blank_value)
    if not success:
        return False
    value = value_cast(value, arg)
    mcs = list(mcs)
    # so the lowest possible chain generates potential errors
    mcs.sort(key=lambda mc: mc.chain_id if mc.chain_id else float("inf"))
    for mc in mcs:
        t = follow_attribute_path_spec(mc, config_opt_names[:-1])
        ident = config_opt_names[-1]
        if not "_final_values" in t.__dict__:
            t._final_values = {ident: arg}
        else:
            if ident in t._final_values:
                if mc is ctx.origin_mc:
                    chainid = max(len(ctx.match_chains), 1)
                elif mc is ctx.defaults_mc:
                    chainid = ""
                else:
                    chainid = mc.chain_id
                error(
                    f"{argname}{chainid} specified twice in: '{t._final_values[ident]}' and '{arg}'")
            t._final_values[ident] = arg
        t.__dict__[ident] = value

    return True


def get_arg_val(arg):
    return arg[arg.find("=") + 1:]


def parse_bool_arg(v, arg, blank_val=True):
    v = v.strip().lower()
    if v == "" and blank_val is not None:
        return blank_val

    if v in yes_indicating_strings:
        return True
    if v in no_indicating_strings:
        return False
    error(f"cannot parse '{v}' as a boolean in '{arg}'")


def parse_int_arg(v, arg):
    try:
        return int(v)
    except ValueError:
        error(f"cannot parse '{v}' as an integer in '{arg}'")


def parse_encoding_arg(v, arg):
    if not verify_encoding(v):
        error(f"unknown encoding in '{arg}'")
    return v


def select_variant(val, variants_dict):
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


def parse_variant_arg(val, variants_dict, arg):
    res = select_variant(val, variants_dict)
    if res is None:
        error(
            f"illegal argument '{arg}', valid options for {arg[:len(arg)-len(val)-1]} are: {', '.join(sorted(variants_dict.keys()))}")
    return res


def verify_encoding(encoding):
    try:
        "!".encode(encoding=encoding)
        return True
    except UnicodeEncodeError:
        return False


def apply_doc_arg(ctx, argname, doctype, arg):
    success, mcs, path = parse_mc_arg(ctx, argname, arg)
    if not success:
        return False
    if mcs == [ctx.defaults_mc]:
        extend_chains_above = len(ctx.match_chains)
        mcs = list(ctx.match_chains)
    elif ctx.origin_mc in mcs:
        mcs.remove(ctx.origin_mc)
        extend_chains_above = len(ctx.match_chains)
    else:
        extend_chains_above = None
    doc = Document(
        doctype,
        normalize_link(
            ctx,
            None,
            Document(doctype.url_handling_type(), None, None),
            None,
            path
        ),
        None,
        mcs,
        extend_chains_above
    )
    ctx.docs.append(doc)
    return True


def apply_ctx_arg(ctx, optname, argname, arg, value_parse=lambda v, _arg: v, support_blank=False, blank_val=""):
    if not begins(arg, optname):
        return False
    if len(optname) == len(arg):
        if support_blank:
            val = blank_val
        else:
            error(f"missing '=' and value for option '{optname}'")
    else:
        nc = arg[len(optname):]
        if chain_regex.match(nc):
            error(
                "option '{optname}' does not support match chain specification")
        if nc[0] != "=":
            return False
        val = get_arg_val(arg)
    if ctx.__dict__[argname] is not None:
        error(f"error: {argname} specified twice")
    ctx.__dict__[argname] = value_parse(val, arg)
    return True


def run_repl(ctx):
    # run with initial args
    last_doc = dl(ctx)
    readline.add_history(shlex.join(sys.argv[1:]))
    tty = sys.stdin.isatty()
    while True:
        try:
            line = input("screp> " if tty else "")
        except KeyboardInterrupt:
            if tty:
                print("")
            raise
        except EOFError:
            if tty:
                print("")
            return
        args = shlex.split(line)
        if not len(args):
            continue
        ctx_new = DlContext(blank=True)
        try:
            parse_args(ctx_new, args)
        except ValueError as ex:
            log(ctx, Verbosity.ERROR, str(ex))
        if not ctx_new.docs and last_doc:
            last_doc.extend_chains_above = len(ctx_new.match_chains)
            last_doc.match_chains = list(ctx_new.match_chains)
            ctx_new.docs.append(last_doc)
        obj_apply_defaults(ctx_new, ctx)
        try:
            setup(ctx_new)
            ctx = ctx_new
        except ValueError:
            pass

        last_doc = dl(ctx, last_doc)
        if ctx.exit:
            return


def parse_args(ctx, args):
    for arg in args:
        if (
            arg in ["-h", "--help", "help"]
            or (begins(arg, "help=") and parse_bool_arg(arg[len("help="):], arg))
        ):
            help()
            return 0

         # content args
        if apply_mc_arg(ctx, "cx", ["content", "xpath"], arg):
            continue
        if apply_mc_arg(ctx, "cr", ["content", "regex"], arg):
            continue
        if apply_mc_arg(ctx, "cf", ["content", "format"], arg):
            continue
        if apply_mc_arg(ctx, "cm", ["content", "multimatch"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "cin", ["content", "interactive"], arg, parse_bool_arg, True):
            continue

        if apply_mc_arg(ctx, "cimin", ["cimin"], arg, parse_int_arg, True):
            continue
        if apply_mc_arg(ctx, "cimax", ["cimax"], arg, parse_int_arg, True):
            continue
        if apply_mc_arg(ctx, "cicont", ["ci_continuous"], arg, parse_bool_arg, True):
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
        if apply_mc_arg(ctx, "lm", ["label", "multimatch"], arg, parse_bool_arg, True):
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
        if apply_mc_arg(ctx, "doc", ["document_output_chains"], arg, lambda v, arg: parse_mc_range_as_arg(ctx, arg, v)):
            continue
        if apply_mc_arg(ctx, "dm", ["document", "multimatch"], arg, parse_bool_arg, True):
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

        if apply_ctx_arg(ctx, "--repl", "repl", arg,  parse_bool_arg, True):
            continue

        if apply_ctx_arg(ctx, "exit", "exit", arg,  parse_bool_arg, True):
            continue

        raise ValueError(f"unrecognized option: '{arg}'")


def main():
    ctx = DlContext(blank=True)
    if len(sys.argv) < 2:
        error(f"missing command line options. Consider {sys.argv[0]} --help")
    try:
        parse_args(ctx, sys.argv[1:])
    except ValueError as ex:
        error(str(ex))

    setup(ctx)
    try:
        if ctx.repl:
            run_repl(ctx)
        else:
            dl(ctx)
    finally:
        finalize(ctx)
    return ctx.error_code


if __name__ == "__main__":
    try:
        # to silence: "Setting a profile has been deprecated" on launching tor
        warnings.filterwarnings(
            "ignore", module=".*selenium.*", category=DeprecationWarning)
        exit(main())
    except BrokenPipeError:
        # Python flushes standard streams on exit; redirect remaining output
        # to devnull to avoid another BrokenPipeError at shutdown
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(1)
