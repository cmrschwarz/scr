#!/usr/bin/env python3
from audioop import minmax
from multiprocessing.sharedctypes import Value
from sqlite3 import DataError
import lxml # pip3 install lxml
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
from collections import deque
from enum import Enum, IntEnum
import time
import itertools
import warnings
import copy
def prefixes(str):
    return [str[:i] for i in range(len(str), 0, -1)]

yes_indicating_strings = prefixes("yes") + prefixes("true") + ["1", "+"]
no_indicating_strings = prefixes("no") + prefixes("false") + ["0", "-"]
skip_indicating_strings = prefixes("skip")
next_doc_indicating_strings = prefixes("nextdoc")
edit_indicating_strings = prefixes("edit")
inspect_indicating_strings = prefixes("inspect")

DEFAULT_CPF="{content}\\n"
DEFAULT_CWF="{content}"

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
verbosities_dict = {
    "info": Verbosity.INFO,
    "warn": Verbosity.WARN,
    "error": Verbosity.ERROR,
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
        self.group_dict = {k:(v if v is not None else "") for (k,v) in group_dict.items()}

    def __key(self):
        return [self.value] + self.group_list + sorted(self.group_dict.items())

    def __eq__(x, y):
        return isinstance(y, x.__class__) and x.__key() == y.__key()

    def __hash__(self):
        return hash(self.__key())

def empty_string_to_none(string):
    if string == "": return None
    return string

class Locator:
    def __init__(self, name, additional_format_keys=[]):
        self.name = name
        self.xpath = None
        self.regex = None
        self.format = None
        self.multimatch = True
        self.interactive = False
        self.content_capture_group = None
        self.additional_format_keys = additional_format_keys

    def compile_regex(self):
        if self.regex is None:
            return
        try:
            regex_comp = re.compile(self.regex)
        except re.error as err:
            error(f"{self.name[0]}r is not a valid regex: {err.msg}")
        if regex_comp.groups == 0:
            self.content_capture_group = 0
        elif self.name in regex_comp.groupindex:
            self.content_capture_group = self.name
        elif regex_comp.groups == 1 + len(regex_comp.groupindex):
            named_indices = list(regex_comp.groupindex.values())
            # find the group index that is not part of named_indices
            # algorithm: put each index value at it's array index
            # the array index that does not contain the right value at the end
            # is not present
            named_indices.append(0)
            for i in range(0, len(named_indices)):
                v = named_indices[i] - 1
                if v != i and v != -1:
                    named_indices[i], named_indices[v] = named_indices[v], named_indices[i]

            for i in range(1, regex_comp.groups):
                if named_indices[i] != i + 1:
                    self.content_capture_group = i + 1
                    break
        else:
            self.content_capture_group  = 0
        self.regex = regex_comp

    def setup(self):
        self.xpath = empty_string_to_none(self.xpath)
        self.regex = empty_string_to_none(self.regex)
        self.format = empty_string_to_none(self.format)
        if self.format:
            self.format = unescape_string(self.format, f"{self.name[0]}f")
        self.compile_regex()
        if self.format:
            if self.xpath is None and self.regex is None:
                error(f"cannot specify {self.name[0]}f without {self.name[0]}x or {self.name[0]}r")
            try:
                if self.regex:
                    capture_group_keys = list(self.regex.groupindex.keys())
                    unnamed_regex_group_count = self.regex.groups - len(capture_group_keys)
                else:
                    capture_group_keys = []
                    unnamed_regex_group_count = 0
                known_keys = [self.name] + capture_group_keys + self.additional_format_keys
                key_count = len(known_keys) + unnamed_regex_group_count
                fmt_keys = get_format_string_keys(self.format)
                named_arg_count = 0
                for k in fmt_keys:
                    if k == "":
                        named_arg_count += 1
                        if named_arg_count > key_count:
                            error(f"exceeded number of keys in {self.name[0]}f={self.format}")
                    elif k not in known_keys:
                        error(f"unknown key {{{k}}} in {self.name[0]}f={self.format}")
            except Exception as ex:
                error(f"invalid format string in {self.name[0]}f={self.format}: {str(ex)}")

    def match_xpath(self, src_xml, path, default=[], return_xml_tuple=False):
        if self.xpath is None: return default
        try:
            xpath_matches = src_xml.xpath(self.xpath)
        except lxml.etree.XPathEvalError as ex:
            error(f"aborting! {self.name[0]}x is not a valid xpath")
        except Exception as ex:
            error(
                f"aborting! failed to apply {self.name[0]}x to {path}: "
                + f"{ex.__class__.__name__}:  {str(ex)}"
            )
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
                    except Exception:
                        pass
            else:
                res.append(lxml.html.tostring(xm, encoding="unicode"))
                if return_xml_tuple:
                    res_xml.append(xm)
        if return_xml_tuple:
            return res, res_xml
        return res

    def match_regex(self, val, path, default=[]):
        if self.regex is None or val is None: return default
        res = []
        for m in self.regex.finditer(val):
            res.append(RegexMatch(m.group(self.content_capture_group), list(m.groups()), m.groupdict()))
            if not self.multimatch:
                break
        return res

    def apply_format(self, match, values, keys):
        if self.format is None: return match.value
        return self.format.format(
            *(match.group_list + [match.value] + values),
            **dict(
                [(keys[i], values[i]) for i in range(len(values))] + [(self.name, match.value)] + list(match.group_dict.items())
            )
        )

    def is_unset(self):
        return min([v is None for v in [self.xpath, self.regex, self.format]])

    def apply(self, src, src_xml, path, default=[], values=[], keys=[]):
        if self.is_unset(): return default
        res = []
        for x in self.match_xpath(src_xml, path, [src]):
            for m in self.match_regex(x, path, [RegexMatch(x)]):
                res.append(self.apply_format(m, values, keys))
        return res

class Document:
    def __init__(self, document_type, path, src_mc, target_mcs=None, encoding=None):
        self.document_type = document_type
        self.path = path
        self.encoding = encoding
        self.src_mc = src_mc
        if not target_mcs:
            self.target_mcs = []
        else:
            self.target_mcs = sorted(target_mcs, key=lambda mc: mc.chain_id)

    def __key(self):
        return (self.document_type, self.path, self.encoding, self.output_enciding)

    def __eq__(x, y):
        return isinstance(y, x.__class__) and x.__key() == y.__key()

    def __hash__(self):
        return hash(self.__key())

class MatchChain:
    def __init__(self, ctx, chain_id, blank=False):
        self.cimin = 1
        self.content_escape_sequence = "<END>"
      
        self.cimax = float("inf")
        self.ci_continuous = False
        self.content_save_format = ""
        self.content_print_format = ""
        self.content_write_format = ""
        self.content_raw = True
        self.content_input_encoding = "utf-8"
        self.content_forced_input_encoding = None
        self.content_encoding = "utf-8"
        self.save_path_interactive = False

        self.label_default_format = None
        self.labels_inside_content = None
        self.label_allow_missing = False
        self.allow_slashes_in_labels = False

        self.documents_bfs = False
        self.dimin = 1
        self.dimax = float("inf")
        self.default_document_encoding = "utf-8"
        self.forced_document_encoding = None
        
        self.default_document_scheme = ctx.fallback_document_scheme
        self.prefer_parent_document_scheme = True
        self.forced_document_scheme = None

        self.selenium_strategy = SeleniumStrategy.FIRST

        if blank:
            for k in self.__dict__:
                self.__dict__[k] = None

        self.ctx = ctx
        self.chain_id = chain_id
        self.content = Locator("content", ["di", "ci"])
        self.label = Locator("label", ["di", "ci"])
        self.document = Locator("document", ["di", "ci"])

        self.di = None
        self.ci = None
        self.have_xpath_matching = None
        self.have_label_matching = None
        self.have_content_xpaths = None
        self.have_multidocs = None
        self.have_interactive_matching = None
        self.need_content_enc = None

    def apply_defaults(self, defaults):
        for k, v in self.__dict__.items():
            if v is None:
                self.__dict__[k] = defaults.__dict__[k]


class DlContext:
    def __init__(self):
        self.match_chains = []
        self.docs = []

        self.cookie_file = None
        self.cookie_jar = None

        self.selenium_variant = SeleniumVariant.DISABLED
        self.tor_browser_dir = None
        self.selenium_driver = None
        self.user_agent_random = False
        self.user_agent = None
        self.verbosity = Verbosity.WARN
        
        # stuff that can't be reconfigured (yet)
        self.selenium_timeout_secs = 10
        self.selenium_poll_frequency_secs = 0.3
        self.selenium_content_count_pad_length = 6

        self.fallback_document_scheme = "https"

        self.defaults_mc = MatchChain(self, None)
        self.origin_mc = MatchChain(self, None, blank=True)
        
       

    def is_valid_label(self, label):
        if self.allow_slashes_in_labels: return True
        if "/" in label or "\\" in label: return False
        return True

def error(text):
    sys.stderr.write(text + "\n")
    exit(1)

def unescape_string(txt, context):
    try:
        return txt.encode("utf-8").decode("unicode_escape")
    except Exception as ex:
        error(f"failed to unescape {context}: {str(ex)}")

def log(ctx, verbosity, msg):
    if ctx.verbosity >= verbosity:
        print(msg)

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
                             (args: label, content, content_enc, encoding, document, escape, [di], [ci], [link], <lr capture groups>, <cr capture groups>)
        csf=<format string>  save content to file at the path resulting from the format string, empty to enable
                             (args: label, content, content_enc, encoding, document, escape, [di], [ci], [link], <lr capture groups>, <cr capture groups>)
        cwf=<format string>  format to write to file. defaults to \"{DEFAULT_CWF}\"
                             (args: label, content, content_enc, encoding, document, escape, [di], [ci], [link], <lr capture groups>, <cr capture groups>)
        csin<bool>           giva a promt to edit the save path for a file
        cin=<bool>           give a prompt to ignore a potential content match
        cl=<bool>            treat content match as a link to the actual content
        cesc=<string>        escape sequence to terminate content in cin mode
        cienc=<encoding>     default encoding to assume that content is in
        cfienc=<encoding>    encoding to always assume that content is in, even if http(s) says differently
        cenc=<encoding>      encoding to use for content_enc

    Labels to give each matched content (becomes the filename):
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
        dbfs=<bool>         traverse the matched documents in breadth first order instead of depth first
        din=<bool>          give a prompt to ignore a potential document match
        denc=<encoding>     default document encoding to use for following documents, default is utf-8
        dfenc=<encoding>    force document encoding for following documents, even if http(s) says differently
        dsch=<scheme>       default scheme for urls derived from following documents, defaults to "https"
        dpsch=<bool>        use the parent documents scheme if available, defaults to true unless dsch is specified
        dfsch=<scheme>      force this scheme for urls derived from following documents

    Initial Documents:
        url=<url>           fetch a document from a url, derived document matches are (relative) urls
        file=<path>         fetch a document from a file, derived documents matches are (relative) file pathes
        rfile=<path>        fetch a document from a file, derived documents matches are urls

    Chain Syntax:
        Any option above can restrict the matching chains is should apply to using opt<chainspec>=<value>.
        Use "-" for ranges, "," for multiple specifications, and "^" to except the following chains.
        Examples:
            lf1,3-5=foo     sets "lf" to "foo" for chains 1, 3, 4 and 5.
            lf2-^4=bar      sets "lf" to "bar" for all chains larger than or equal to 2, except chain 4

    Global Options:
        v=<verbosity>       output verbosity levels (default: warn, values: info, warn, error)
        ua=<string>         user agent to pass in the html header for url GETs
        uar=<bool>          use a rangom user agent
        cookiefile=<path>   path to a netscape cookie file. cookies are passed along for url GETs
        sel=<browser>       use selenium to load urls into an interactive browser session
                            (default: disabled, values: tor, chrome, firefox, disabled)
        strat=<browser>     matching strategy for selenium (values: first, new, interactive)
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

def download_url(ctx, url):
   return requests.get(url, cookies=ctx.cookie_jar, headers={'User-Agent': ctx.user_agent})

def setup_selenium_tor(ctx):
    # use bundled geckodriver if available
    cwd = add_cwd_to_path()
    if ctx.tor_browser_dir is None:
        tb_env_var = "TOR_BROWSER_DIR"
        if tb_env_var in os.environ:
            ctx.tor_browser_dir = os.environ[tb_env_var]
        else:
            error(f"error! no tbdir specified, check --help")
    try:
        options = webdriver.firefox.options.Options()
        if ctx.user_agent != None:
            options.set_preference("general.useragent.override", ctx.user_agent)
            # otherwise the user agent is not applied
            options.set_preference("privacy.resistFingerprinting", False)
        ctx.selenium_driver = TorBrowserDriver(ctx.tor_browser_dir, tbb_logfile_path=os.devnull, options=options)
    except Exception as ex:
        error(f"failed to start tor browser: {str(ex)}")
    os.chdir(cwd) #restore cwd that is changed by tor for some reason

def setup_selenium_firefox(ctx):
    # use bundled geckodriver if available
    add_cwd_to_path()
    options = webdriver.FirefoxOptions()
    if ctx.user_agent != None:
        options.set_preference("general.useragent.override", ctx.user_agent)
    try:
        ctx.selenium_driver = webdriver.Firefox(options=options)
    except Exception as ex:
        error(f"failed to start geckodriver: {str(ex)}")
    ctx.selenium_driver.set_page_load_timeout(ctx.selenium_timeout_secs)

def setup_selenium_chrome(ctx):
    # allow usage of bundled chromedriver
    add_cwd_to_path()
    options = webdriver.ChromeOptions()
    options.add_argument("--incognito")
    if ctx.user_agent != None:
        options.add_argument(f"user-agent={ctx.user_agent}")
    try:
        ctx.selenium_driver = webdriver.Chrome(options=options)
    except Exception as ex:
        error(f"failed to start chromedriver: {str(ex)}")
    ctx.selenium_driver.set_page_load_timeout(ctx.selenium_timeout_secs)



def setup_selenium(ctx):
    if ctx.selenium_variant == SeleniumVariant.DISABLED:
        ctx.selenium_strategy = SeleniumStrategy.DISABLED
        return
    elif ctx.selenium_variant == SeleniumVariant.TORBROWSER:
        setup_selenium_tor(ctx)
    elif ctx.selenium_variant == SeleniumVariant.CHROME:
        setup_selenium_chrome(ctx)
    elif ctx.selenium_variant == SeleniumVariant.FIREFOX:
        setup_selenium_firefox(ctx)
    else:
        assert False

    if ctx.cookie_jar:
        for cookie in ctx.cookie_jar:
            cookie_dict = {
                'domain': cookie.domain,
                'name': cookie.name,
                'value': cookie.value,
                'secure': cookie.secure
            }
            if cookie.expires:
                cookie_dict['expiry'] = cookie.expires
            if cookie.path_specified:
                cookie_dict['path'] = cookie.path
            ctx.selenium_driver.add_cookie(cookie_dict)

def get_format_string_keys(fmt_string):
    return [f for (_, f, _, _) in Formatter().parse(fmt_string) if f is not None]

def format_string_uses_arg(fmt_string, arg_pos, arg_name):
    if fmt_string is None: return False
    fmt_args = get_format_string_keys(fmt_string)
    return (arg_name in fmt_args or fmt_args.count("") > arg_pos)

def setup_match_chain(mc):
    mc.apply_defaults(mc.ctx.defaults_mc)
    locators = [mc.content, mc.label, mc.document]
    for l in locators:
        l.setup()

    if mc.dimin > mc.dimax: error(f"dimin can't exceed dimax")
    if mc.cimin > mc.cimax: error(f"cimin can't exceed cimax")
    mc.ci = mc.cimin
    mc.di = mc.dimin

    if not mc.content_print_format and not mc.content_save_format:
        mc.content_print_format = DEFAULT_CPF
    if mc.content_write_format and not mc.content_save_format:
        error(f"cannot specify cwf without csf")

    if not mc.content_write_format:
        mc.content_write_format = DEFAULT_CWF

    if mc.content_print_format:
        mc.content_print_format = unescape_string(mc.content_print_format, "cpf")
    if mc.content_save_format:
        mc.content_save_format = unescape_string(mc.content_save_format, "csf")
        mc.content_write_format = unescape_string(mc.content_write_format, "cwf")

    mc.have_xpath_matching = max([l.xpath is not None for l in locators])
    mc.have_label_matching = mc.label.xpath is not None or mc.label.regex is not None
    mc.have_content_xpaths = mc.labels_inside_content is not None and mc.label.xpath is not None
    mc.have_multidocs = mc.document.xpath is not None or mc.document.regex is not None or mc.document.format is not None
    mc.have_interactive_matching = mc.label.interactive or mc.content.interactive

    if not mc.have_label_matching:
        mc.label_allow_missing = True
        if mc.labels_inside_content:
            error(f"cannot specify lic without lx or lr")

    if mc.label_default_format is None and mc.label_allow_missing:
        form = "dl_"
        # if max was not set it is 'inf' which has length 3 which is a fine default
        didigits = max(len(str(mc.dimin)), len(str(mc.dimax)))
        cidigits = max(len(str(mc.dimin)), len(str(mc.dimax)))
        if mc.ci_continuous:
            form += f"{{ci:0{cidigits}}}"
        elif mc.content.multimatch:
            if mc.have_multidocs:
                form += f"{{di:0{didigits}}}_{{ci:0{cidigits}}}"
            else:
                form += f"{{ci:0{cidigits}}}"

        elif mc.have_multidocs:
            form += f"{{di:0{didigits}}}"

        mc.label_default_format = form

    mc.need_content_enc = (
        format_string_uses_arg(mc.content_save_format, 3, "content_enc")
        or format_string_uses_arg(mc.content_write_format, 3, "content_enc")
        or format_string_uses_arg(mc.content_print_format, 3, "content_enc")
    )
    if not mc.content_raw:
        if mc.content_save_format:
            mc.content_download_required = True

        if mc.content_print_format and not mc.content_download_required:
            mc.content_download_required = mc.need_content_enc or format_string_uses_arg(mc.content_print_format, 2, "content")


def setup(ctx):
    global DEFAULT_CPF
    if len(ctx.docs) == 0:
        error("must specify at least one url or (r)file")

    if ctx.cookie_file is not None:
        try:
            ctx.cookie_jar = MozillaCookieJar()
            ctx.cookie_jar.load(ctx.cookie_file, ignore_discard=True,ignore_expires=True)
        except Exception as ex:
            error(f"failed to read cookie file: {str(ex)}")
    if ctx.user_agent is None and ctx.user_agent_random:
        error(f"the options ua and uar are incompatible")
    elif ctx.user_agent_random:
        user_agent_rotator = UserAgent()
        ctx.user_agent = user_agent_rotator.get_random_user_agent()
    elif ctx.user_agent is None and ctx.selenium_variant == SeleniumVariant.DISABLED:
        ctx.user_agent = "dl.py/0.0.1"
    
    # if no chains are specified, use the origin chain as chain 0
    if not ctx.match_chains:
        ctx.match_chains.append(ctx.origin_mc)
        ctx.origin_mc.chain_id = 0

    for mc in ctx.match_chains:
        setup_match_chain(mc)

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
            option_names = [o[1][0] for o in options]
            print("please answer with " + ", ".join(option_names[:-1]) + " or " + option_names[-1])
            continue
        return res

def prompt_yes_no(prompt_text, default=None):
    return prompt(prompt_text, [(True, yes_indicating_strings), (False, no_indicating_strings)], default)
def fetch_doc(ctx, doc, raw=False, enc=True, nosingle=False):
    if doc.document_type in [DocumentType.FILE, DocumentType.RFILE]:
        with open(doc.path, "rb") as f:
            data = f.read()
        data_enc = str(data, encoding=doc.encoding)
    else:
        assert doc.document_type == DocumentType.URL
        if ctx.selenium_variant != SeleniumVariant.DISABLED:
            if not raw:
                ctx.selenium_driver.get(doc.path)
                data_enc = ctx.selenium_driver.page_source
            else:
                error("downloading content in selenium mode is not supported yet")
        else:
            res = download_url(ctx, doc.path)
            data = res.content
            if enc:
                if doc.force_encoding:
                    try:
                        data_enc = str(data, encoding=doc.encoding)
                    except Exception:
                        data_enc = res.text
                else:
                    data_enc = res.text
                    if res.encoding is not None:
                        doc.encoding = res.encoding

            res.close()
            if data is None:
                raise ValueError("empty response")
    result = []
    if raw: result.append(data)
    if enc: result.append(data_enc)
    if not nosingle and len(result) == 1: return result[0]
    return tuple(result)

def gen_final_content_format(ctx, format_str, label_txt, di, ci, content_link, content, content_enc, label_regex_match, content_regex_match, doc):
    opts_list = []
    opts_dict = {}
    if ctx.document.multimatch:
        opts_list.append(di)
        opts_dict["di"] = di
    if ctx.content.multimatch:
        opts_list.append(ci)
        opts_dict["ci"] = ci
    if content_link:
        opts_list.append(content_link)
        opts_dict["link"] = content_link


    if label_regex_match is None:
        label_regex_match = RegexMatch(None)
    if content_regex_match is None:
        content_regex_match = RegexMatch(None)
    # args: label, content, encoding, document, escape, [url], <lr capture groups>, <cr capture groups>
    args_list = ([label_txt, content, content_enc, doc.encoding, doc.path, ctx.content_escape_sequence]
        + opts_list + label_regex_match.group_list + content_regex_match.group_list)
    args_dict = dict(
        list(content_regex_match.group_dict.items())
        + list(label_regex_match.group_dict.items())
        + list(opts_dict.items())
        + list(
            {
            "label": label_txt,
            "content": content,
            "content_enc": content_enc,
            "encoding": doc.encoding,
            "document": doc.path,
            "escape": ctx.content_escape_sequence
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
                res += format(val, format_args).encode("utf-8")
    return res


def normalize_link(ctx, mc, src_doc, link):
    # todo: make this configurable
    if src_doc.document_type == DocumentType.FILE:
        return link
    url_parsed = urllib.parse.urlparse(link)
    doc_url_parsed = urllib.parse.urlparse(src_doc.path) if src_doc.path else None

    if doc_url_parsed and url_parsed.netloc == "" and src_doc.document_type == DocumentType.URL:
        url_parsed = url_parsed._replace(netloc=doc_url_parsed.netloc)

    # for urls like 'google.com' urllib makes this a path instead of a netloc
    if url_parsed.netloc == "" and not doc_url_parsed and url_parsed.scheme == "" and url_parsed.path != "" and link[0] not in [".", "/"]:
        url_parsed = url_parsed._replace(path="", netloc=url_parsed.path)
    if (mc and mc.forced_document_scheme):
        url_parsed = url_parsed._replace(scheme=mc.forced_document_scheme)
    elif url_parsed.scheme == "":
        if (mc and mc.prefer_parent_scheme) and doc_url_parsed and doc_url_parsed.scheme != "":
            scheme = doc_url_parsed.scheme
        elif mc and mc.default_document_scheme:
            scheme = mc.default_document_scheme
        else:
            scheme = ctx.fallback_document_scheme
        url_parsed = url_parsed._replace(scheme=scheme)
    return url_parsed.geturl()

def handle_content_match(ctx, doc, content_match, di, ci):
    label_regex_match = content_match.label_regex_match
    content_txt = ctx.content.apply_format(
        content_match.content_regex_match,
        [di, ci],
        ["di", "ci"],
    )

    if label_regex_match is None:
        label = ctx.label_default_format.format([di, ci], di=di, ci=ci)
    else:
        label = ctx.label.apply_format(label_regex_match, [di, ci], ["di", "ci"])
    document_context = f'document "{doc.path}"'
    if ctx.have_multidocs:
        if ctx.content.multimatch:
            document_context += f" (di={di}, ci={ci})"
        else:
            document_context += f" (di={di})"
    else:
        if ctx.content.multimatch:
            document_context += f" (ci={ci})"

    if ctx.content_raw:
        context = document_context
        content_link = None
    else:
        content_link = content_txt

    while True:
        if not ctx.content_raw:
            content_link = normalize_link(ctx, doc, content_link)
            context = f'content link "{content_link}"'

        if ctx.content.interactive:
            res = prompt(
                f'accept {context} (label "{label}") [Yes/edit/skip/nextdoc]? ',
                [(1, yes_indicating_strings), (2, edit_indicating_strings), (3, skip_indicating_strings), (4, next_doc_indicating_strings)],
                1
            )
            if res == 1: break
            if res == 3: return False
            if res == 4: return None
            assert res == 2
            if not ctx.content_raw:
                content_link = input("enter new content link:\n")
            else:
                sys.stdout.write(f'enter new content (terminate with a newline followed by the string "{ctx.content_escape_sequence}"):\n')
                content_txt = ""
                while True:
                    content_txt += input() + "\n"
                    i = content_txt.find("\n" + ctx.content_escape_sequence)
                    if i != -1:
                        content_txt = content_txt[:i]
                        break
        break

    if ctx.label.interactive:
        while True:
            if not ctx.is_valid_label(label):
                sys.stderr.write(f'"{doc.path}": labels cannot contain a slash ("{label}")')
            else:
                res = prompt(
                    f'{context}: accept label "{label}" [Yes/edit/inspect/skip/nextdoc]? ',
                    [
                        (1, yes_indicating_strings),
                        (2, edit_indicating_strings),
                        (3, inspect_indicating_strings),
                        (4, skip_indicating_strings),
                        (5, next_doc_indicating_strings)
                    ],
                    1
                )
                if res == 1: break
                if res == 5: return None
                if res == 3:
                    print(f'"{doc.path}": content for "{label}":\n' + content_txt)
                    continue
                if res == 4:
                    return False
                assert res == 2
            label = input("enter new label: ")

    if not ctx.content_raw:
        try:
            if ctx.content_download_required:
                res = fetch_doc(
                    ctx,
                    Document(
                        doc.document_type.derived_type(),
                        content_link, ctx.content_input_encoding,
                        ctx.content_forced_input_encoding,
                        None, False, False,
                    ),
                    raw=True,
                    enc=ctx.need_content_enc,
                    nosingle=True
                )
                if res is None:
                    return False
                content_bytes = res[0]
                content_txt = res[1] if ctx.need_content_enc else None
            else:
                content_bytes = None
                content_txt = None
        except Exception as ex:
            sys.stderr.write(f'{document_context}: failed to fetch content from "{content_link}"\n')
            return False
    else:
        content_bytes = content_txt

    if ctx.need_content_enc:
        content_enc = content_txt.encode(ctx.content_encoding)
    else:
        content_enc = None


    if ctx.content_print_format:
        print_data = gen_final_content_format(
            ctx, ctx.content_print_format, label, di, ci, content_link,
            content_bytes, content_enc,
            content_match.label_regex_match, content_match.content_regex_match,
            doc
        )
        sys.stdout.buffer.write(print_data)

    if ctx.content_save_format:
        if not ctx.is_valid_label(label):
            sys.stderr.write(f"matched label '{label}' would contain a slash, skipping this content from: {doc.path}")
        save_path = gen_final_content_format(
            ctx, ctx.content_save_format, label, di, ci, content_link,
            content_bytes, content_enc,
            content_match.label_regex_match, content_match.content_regex_match,
            doc
        )
        try:
            save_path = save_path.decode("utf-8")
        except Exception:
            log(ctx. Verbosity.ERROR, f"{context}: generated save path is not valid utf-8")
            save_path = None
        while True:
            if save_path and not os.path.exists(os.path.dirname(os.path.abspath(save_path))):
                log(ctx. Verbosity.ERROR, f"{context}: directory of generated save path does not exist")
                save_path = None
            if not save_path and not ctx.save_path_interactive:
                return False
            if not ctx.save_path_interactive:
                break
            if save_path:
                res = prompt(
                    f'{context}: accept save path "{save_path}" [Yes/edit/skip/nextdoc]? ',
                    [
                        (1, yes_indicating_strings),
                        (2, edit_indicating_strings),
                        (3, skip_indicating_strings),
                        (4, next_doc_indicating_strings)
                    ],
                    1
                )
                if res == 1: break
                if res == 4: return None
                if res == 3: return False
                assert res == 2
            save_path = input("enter new save path: ")
        try:
            f = open(save_path, "wb")
        except Exception as ex:
            error(
                f"{context}: aborting! failed to write to file '{save_path}': {ex.msg}")

        try:
            f = open(save_path, "wb")
        except Exception as ex:
            error(
                f"{context}: aborting! failed to write to file '{save_path}': {ex.msg}")

        write_data = gen_final_content_format(
            ctx, ctx.content_write_format, label, di, ci, content_link,
            content_bytes, content_enc,
            content_match.label_regex_match, content_match.content_regex_match,
            doc
        )
        f.write(write_data)
        f.close()
        log(ctx, Verbosity.INFO, f"wrote content into {save_path} for {context}")
    return True

def handle_document_match(ctx, doc, matched_path):
    if not ctx.document.interactive: return True
    res = prompt(
        f'accept matched document "{matched_path}" [Yes/no/edit]? ',
        [(1, yes_indicating_strings), (2, no_indicating_strings), (3, edit_indicating_strings)],
        1
    )
    if res == 1:
        return matched_path
    if res == 2:
        return None
    if res == 3:
        return input("enter new document: ")

def gen_content_matches(ctx, doc, src, src_xml):
    content_matches = []

    if ctx.have_content_xpaths:
        contents, contents_xml = ctx.content.match_xpath(src_xml, doc.path, ([doc.src], [src_xml]), True)
    else:
        contents = ctx.content.match_xpath(src_xml, doc.path, [src])

    labels = []
    if ctx.have_label_matching and not ctx.labels_inside_content:
        for lx in ctx.label.match_xpath(src_xml, doc.path, [src]):
            labels.extend(ctx.label.match_regex(src, doc.path, [RegexMatch(lx)]))
    match_index = 0
    labels_none_for_n = 0
    for content in contents:
        content_regex_matches = ctx.content.match_regex(content, doc.path, [RegexMatch(content)])
        if ctx.labels_inside_content and ctx.label.xpath:
            content_xml = contents_xml[match_index] if ctx.have_content_xpaths else None
            labels = []
            for lx in ctx.label.match_xpath(content_xml, doc.path, [src]):
                labels.extend(ctx.label.match_regex(src, doc.path, [RegexMatch(lx)]))
            if len(labels) == 0:
                if not ctx.label_allow_missing:
                    labels_none_for_n += len(content_regex_matches)
                    continue
                label = None
            else:
                label = labels[0]

        for crm in content_regex_matches:
            if ctx.labels_inside_content:
                if not ctx.label.xpath:
                    labels = ctx.label.match_regex(crm.value, doc.path, [RegexMatch(crm.value)])
                    if len(labels) == 0:
                        if not ctx.label_allow_missing:
                            labels_none_for_n += 1
                            continue
                        label = None
                    else:
                        label = labels[0]
            else:
                if not ctx.label.multimatch and len(labels) > 0:
                    label = labels[0]
                elif match_index in labels:
                    label = labels[match_index]
                elif not ctx.label_allow_missing:
                    labels_none_for_n += 1
                    continue
                else:
                    label = None

            content_matches.append(ContentMatch(label, crm))
        match_index += 1
    return content_matches, labels_none_for_n

def gen_document_matches(ctx, doc, src, src_xml):
    new_paths = ctx.document.apply(src, src_xml, doc.path)
    return [
        Document(
            doc.document_type.derived_type(),
            path,
            doc.encoding,

        )
        for path in new_paths
    ]

def dl(ctx):
    docs = deque(ctx.docs)
    handled_content_matches = {}
    handled_document_matches = {}
    doc = None
    while docs:
        content_matches_in_doc = False
        document_matches_in_doc = False
        if doc:
            for mc in doc.target_mcs:
                mc.di += 1
        doc = docs.popleft()
        match_chains = list(doc.target_mcs)
        try_number = 0
        final_document_matches = []
        final_content_matches = []
        try:
            src = fetch_doc(ctx, doc)
        except Exception as ex:
            log(ctx, Verbosity.ERROR, f"Failed to fetch {doc.path}")
            continue
        static_content = (doc.document_type != DocumentType.URL)
        input_timeout = None if static_content else ctx.selenium_poll_frequency_secs
        last_msg = ""
        while True:
            accept = False
            try_number += 1
            same_content = static_content and try_number > 1
            if try_number > 1 and not static_content:
                assert ctx.selenium_variant != SeleniumVariant.DISABLED
                try:
                    src_new = ctx.selenium_driver.page_source
                    same_content = (src_new == src)
                    src = src_new
                except Exception:
                    same_content = False
                    src = ""

            if not same_content:
                try:
                    src_xml = lxml.html.fromstring(src) if ctx.have_xpath_matching else None
                    content_matches, labels_none_for_n = gen_content_matches(ctx, doc, src, src_xml)
                except Exception:
                    content_matches = []
                    labels_none_for_n = 0
                document_matches = []
                if di <= ctx.dimax:
                    document_matches = gen_document_matches(ctx, doc, src, src_xml)

                if ctx.selenium_strategy == SeleniumStrategy.FIRST:
                    if not content_matches or (not document_matches and (ctx.have_multidocs and di < ctx.dimax)):
                        time.sleep(ctx.selenium_poll_frequency_secs)
                        continue
                    accept = True
                elif ctx.selenium_strategy == SeleniumStrategy.DISABLED:
                    accept = True

                if ctx.selenium_strategy != SeleniumStrategy.DEDUP:
                    final_content_matches = content_matches
                    final_document_matches = document_matches
                else:
                    for cm in content_matches:
                        if cm in handled_content_matches:
                            continue
                        handled_content_matches[cm] = None
                        final_content_matches.append(cm)

                    for dm in document_matches:
                        if dm in handled_document_matches:
                            continue
                        handled_document_matches[dm] = None
                        final_document_matches.append(dm)



            if ctx.selenium_strategy in [SeleniumStrategy.INTERACTIVE, SeleniumStrategy.DEDUP] and not static_content:
                content_count = len(final_content_matches)
                docs_count = len(final_document_matches)
                msg = ""
                content_count_pad_len = (
                    ctx.selenium_content_count_pad_length
                    - min(len(str(content_count)), ctx.selenium_content_count_pad_length)
                )
                rpad = int(content_count_pad_len / 2)
                lpad = content_count_pad_len - rpad
                msg += f'"{doc.path}": accept {lpad * " "} < {content_count} > {rpad * " "} content'
                if content_count != 1:
                    msg += "s"
                else:
                    msg += " "

                if labels_none_for_n != 0:
                    msg += f" (missing {labels_none_for_n} labels)"
                if ctx.have_multidocs and di <= ctx.dimax:
                    msg += f" and {docs_count} document"
                    if docs_count != 1:
                        msg += "s"
                msg += " [Yes/skip]? "

                if msg != last_msg:
                    msg_full = "\r" + " " * len(last_msg) + "\r" + msg
                    last_msg = msg
                    msg = msg_full
                else:
                    msg = None
                rlist = []
                if try_number > 1:
                    rlist, _, _ = select.select([sys.stdin], [], [], input_timeout)
                if not rlist and msg:
                    sys.stdout.write(msg)

                if not rlist:
                    rlist, _, _ = select.select([sys.stdin], [], [], input_timeout)
                if rlist:
                    accept = parse_prompt_option(sys.stdin.readline(), [(True, yes_indicating_strings), (False, skip_indicating_strings + no_indicating_strings)], True)
                    if accept is None:
                        print("please answer with yes or skip")
                        sys.stdout.write(msg)
                        continue
                    break
            if accept:
                break

        if accept == False:
            continue

        if not ctx.ci_continuous:
            ci = ctx.cimin
        for i, cm in enumerate(final_content_matches):
            if not ctx.have_label_matching or cm.label_regex_match is not None:
                content_matches_in_doc = True
                accept = handle_content_match(ctx, doc, cm, di, ci)
                if accept is None:
                    break
                if accept:
                    ci += 1
                if ci > ctx.cimax: break
            else:
                log(ctx, Verbosity.WARN, f"no labels! skipping remaining {len(final_content_matches) - i} content element(s) in document:\n    {doc.path}")
                break
        if not ctx.have_interactive_matching and not content_matches_in_doc:
            log(ctx, Verbosity.WARN, f"no content matches for document: {doc.path}")
        if not ctx.document.interactive and di < ctx.dimax and not document_matches_in_doc and ctx.have_multidocs:
            log(ctx, Verbosity.WARN, f"no document matches for document: {doc.path}")
        if di < ctx.dimax :
            final_document_matches = [d for d in final_document_matches if handle_document_match(ctx, doc, d.path)]
            if ctx.documents_bfs:
                docs.extend(final_document_matches)
            else:
                docs.extendleft(final_document_matches)
        di += 1

    if di <= ctx.dimax and ctx.dimax != float("inf") :
        log(ctx, Verbosity.WARN, "exiting! all documents handled before dimax was reached")


def begins(string, begin):
    return len(string) >= len(begin) and string[0:len(begin)] == begin

def parse_mc_range_int(ctx, v, arg):
    try:
        return int(v)
    except ValueError:
        error(f"failed to parse '{v}' as an integer for match chain specification of '{arg}'")

def extend_match_chain_list(ctx, needed_id):
    if len(ctx.match_chains) > needed_id: return
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
            error("invalid empty range in match chain specification of '{arg}'")
        dash_split = [r.strip() for r in s.split("-")]
        if len(dash_split) > 2 or s == "-":
            error("invalid range '{s}' in match chain specification of '{arg}'")
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
               snd = len(ctx.match_chains) - 1
               ranges.append([ctx.origin_mc])
            else:
                snd = parse_mc_range_int(ctx, dash_split[1], arg)
                if fst > snd:
                    error(f"second value must be larger than first for range {s} in match chain specification of '{arg}'")
                extend_match_chain_list(ctx, snd)
            ranges.append((ctx.match_chains[i] for i in range(fst, snd + 1)))
    return itertools.chain(*ranges)

def parse_mc_range(ctx, mc_spec, arg):
    if mc_spec == "":
        return itertools.chain(ctx.match_chains, [ctx.origin_mc])
    
    esc_split = [x.strip() for x in mc_spec.split("^")]
    if len(esc_split) > 2:
        error(f"cannot have more than one '^' in match chain specification of '{arg}'")
    if len(esc_split) == 1: 
        return parse_simple_mc_range(ctx, mc_spec, arg)
    lhs, rhs = esc_split
    if lhs == "":
        include = itertools.chain(ctx.match_chains, [ctx.origin_mc])
    else:
        include = parse_simple_mc_range(ctx, lhs, arg)
    return ({*include} - {*parse_simple_mc_range(ctx, rhs, arg)})


def parse_mc_arg(ctx, argname, arg, support_blank=False, blank_value=""):
    if not begins(arg, argname): return False, None, None
    argname_len = len(argname)
    eq_pos = arg.find("=")
    if eq_pos == -1:
        if not support_blank:
            error("missing equals sign in argument '{arg}'")
        pre_eq_arg = arg
        value = blank_value
        mc_spec =  arg[argname_len:]
    else:
        pre_eq_arg = arg[:eq_pos]
        mc_spec = arg[argname_len: eq_pos]
        value = arg[eq_pos+1:]
    return True, parse_mc_range(ctx, mc_spec, pre_eq_arg), value

def apply_mc_arg(ctx, argname, config_opt_names, arg, value_cast=lambda x, _arg: x,support_blank=False, blank_value=""):
    success, mcs, value = parse_mc_arg(ctx, argname, arg, support_blank, blank_value)
    if not success: return False
    value = value_cast(value, arg)
    for mc in mcs:
        t = mc
        for n in config_opt_names[:-1]:
            t = t.__dict__[n]
        t.__dict__[config_opt_names[-1]] = value
    return True

def get_arg_val(arg):
    return arg[arg.find("=") + 1:]

def parse_bool_arg(v, arg, blank_val=True):
    if v == "" and blank_val is not None:
        return blank_val
    try:
        return bool(v)
    except ValueError:
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
    if val == "": return None
    if val in variants_dict: return variants_dict[val]
    match = None
    for k, v in variants_dict.items():
        if begins(k, val):
            if match is not None: return None
            match = v
    return match

def parse_variant_arg(val, variants_dict, arg):
    res = select_variant(val, variants_dict)
    if res is None:
        error(f"no matching selenium variant for '{arg}'")
    return res

def verify_encoding(encoding):
    try:
        "!".encode(encoding=encoding)
        return True
    except Exception:
        return False

def apply_doc_arg(ctx, argname, doctype, arg):
    success, mcs, value = parse_mc_arg(ctx, argname, arg)
    if success:
        doc = Document(
            doctype,
            normalize_link(ctx, None, Document(doctype.url_handling_type(), None, None), value),
            None,
            list(mcs)
        )
        ctx.docs.append(doc)
    return success

def apply_ctx_arg(ctx, optname, argname, arg, value_parse=lambda v, _arg: v, support_blank=False, blank_val=""):
    if not begins(arg, f"{optname}"): return False
    if len(optname) == len(arg):
        if support_blank:
            val = blank_val
        else:
            error("missing '=' and value for option {optname}")
    else:
        nc = arg[len(optname)]
        if nc == "-" or nc in range(0,10):
            error("option '{optname}' does not support match chain specification")
        if nc != "=":
            error("unknown option '{arg}'")
        val = get_arg_val(arg)
    ctx.__dict__[argname] = value_parse(val, arg)
    return True

def main():
    ctx = DlContext()
    if len(sys.argv) < 2:
        error(f"missing command line options. Consider {sys.argv[0]} --help")

    for arg in sys.argv[1:]:
        if arg == "--help" or arg=="-h":
            help()
            return 0

         # content args
        if apply_mc_arg(ctx, "cx", ["content", "xpath"], arg): continue
        if apply_mc_arg(ctx, "cr", ["content", "regex"], arg): continue
        if apply_mc_arg(ctx, "cf", ["content", "format"], arg): continue
        if apply_mc_arg(ctx, "cm", ["content", "multimatch"], arg, parse_bool_arg): continue
        if apply_mc_arg(ctx, "cin", ["content", "interactive"], arg, parse_bool_arg): continue

        if apply_mc_arg(ctx, "cimin", ["cimin"], arg, parse_int_arg): continue
        if apply_mc_arg(ctx, "cimax", ["cimax"], arg, parse_int_arg): continue
        if apply_mc_arg(ctx, "cicont", ["ci_continuous"], arg, parse_bool_arg): continue

        if apply_mc_arg(ctx, "cipf", ["content_print_format"], arg, parse_bool_arg): continue
        if apply_mc_arg(ctx, "cwf", ["content_write_format"], arg): continue
        if apply_mc_arg(ctx, "csf", ["content_save_format"], arg): continue
        if apply_mc_arg(ctx, "csin", ["save_path_interactive"], arg, parse_bool_arg): continue

        if apply_mc_arg(ctx, "cenc", ["content_encoding"], arg, parse_encoding_arg): continue
        if apply_mc_arg(ctx, "cienc", ["content_input_encoding"], arg, parse_encoding_arg): continue
        if apply_mc_arg(ctx, "cfienc", ["content_forced_input_encoding"], arg, parse_encoding_arg): continue

        if apply_mc_arg(ctx, "cl", ["content_raw"], arg, lambda v, arg: not parse_bool_arg(v, arg)): continue
        if apply_mc_arg(ctx, "cesc", ["content_escape_sequence"], arg): continue


        # label args
        if apply_mc_arg(ctx, "lx", ["label", "xpath"], arg): continue
        if apply_mc_arg(ctx, "lr", ["label", "regex"], arg): continue
        if apply_mc_arg(ctx, "lf", ["label", "format"], arg): continue
        if apply_mc_arg(ctx, "lm", ["label", "multimatch"], arg, parse_bool_arg, True): continue
        if apply_mc_arg(ctx, "lin", ["label", "interactive"], arg, parse_bool_arg, True): continue
        if apply_mc_arg(ctx, "las", ["allow_slashes_in_labels"], arg, parse_bool_arg, True): continue
        if apply_mc_arg(ctx, "lic", ["labels_inside_content"], arg, parse_bool_arg, True): continue
        if apply_mc_arg(ctx, "lam", ["label_allow_missing"], arg, parse_bool_arg, True): continue


        # document args
        if apply_mc_arg(ctx, "dx", ["document", "xpath"], arg): continue
        if apply_mc_arg(ctx, "dr", ["document", "regex"], arg): continue
        if apply_mc_arg(ctx, "df", ["document", "format"], arg): continue
        if apply_mc_arg(ctx, "dm", ["document", "multimatch"], arg, parse_bool_arg, True): continue
        if apply_mc_arg(ctx, "din", ["document", "interactive"], arg, parse_bool_arg, True): continue

        if apply_mc_arg(ctx, "dimin", ["dimin"], arg, parse_int_arg): continue
        if apply_mc_arg(ctx, "dimax", ["dimax"], arg, parse_int_arg): continue

        if apply_mc_arg(ctx, "owf", ["overwrite_files"], arg, parse_bool_arg, True): continue

        if apply_mc_arg(ctx, "denc", ["default_document_encoding"], arg, parse_encoding_arg): continue
        if apply_mc_arg(ctx, "dfenc", ["forced_document_encoding"], arg,parse_encoding_arg): continue
        
        if apply_mc_arg(ctx, "dsch", ["default_document_scheme"], arg): continue
        if apply_mc_arg(ctx, "dpsch", ["prefer_parent_document_scheme"], arg): continue
        if apply_mc_arg(ctx, "dfsch", ["forced_document_scheme"], arg): continue

        if apply_mc_arg(ctx, "strat", ["selenium_strategy"], arg, lambda v, arg: parse_variant_arg(v, selenium_strats_dict, arg)): continue
        
        # misc args
        if apply_doc_arg(ctx, "url", DocumentType.URL, arg): continue
        if apply_doc_arg(ctx, "rfile", DocumentType.RFILE, arg): continue
        if apply_doc_arg(ctx, "file", DocumentType.FILE, arg): continue

        if apply_ctx_arg(ctx, "cookiefile", "cookie_file", arg): continue
        if apply_ctx_arg(ctx, "sel", "cookie_file", arg): continue

        if apply_ctx_arg(ctx, "sel", "selenium_variant", arg, lambda v, arg: parse_variant_arg(v, selenium_variants_dict, arg)): continue
        if apply_ctx_arg(ctx, "tbdir", "tor_browser_dir", arg): continue # implies sel=t
        if apply_ctx_arg(ctx, "dbfs", "documents_bfs", arg, parse_bool_arg, True): continue
        if apply_ctx_arg(ctx, "ua", "user_agent", arg): continue
        if apply_ctx_arg(ctx, "ua", "user_agent_random", parse_bool_arg, True): continue
        if apply_ctx_arg(ctx, "v", "verbosity", arg, lambda v, arg: parse_variant_arg(v, verbosities_dict, arg)): continue

        if "=" not in arg:
            error(f"unrecognized option: '{arg}', are you missing an equals sign?")
        else:
            error(f"unrecognized option: '{arg}'. Consider {sys.argv[0]} --help")
    setup(ctx)
    dl(ctx)
    return 0


if __name__ == "__main__":
    # to silence: "Setting a profile has been deprecated" on launching tor
    warnings.filterwarnings("ignore", module=".*selenium.*", category=DeprecationWarning)
    exit(main())