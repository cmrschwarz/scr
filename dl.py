#!/usr/bin/env python3
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
from selenium.webdriver.common.by import By as SeleniumLookupBy
from collections import deque
from enum import Enum, IntEnum
import time
import warnings
import datetime

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

class SeleniumStrategy(Enum):
    DISABLED = 0
    FIRST = 1
    ASK = 2
    DEDUP = 3

class Verbosity(IntEnum):
    SILENT = 0
    ERROR = 1
    WARN = 2
    INFO = 3

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
        self.regex_groups = False
        self.additional_format_keys = additional_format_keys

    def compile_regex(self):
        if self.regex is None:
            return
        try:
            regex_comp = re.compile(self.regex)
        except re.error as err:
            error(f"{self.name[0]}r is not a valid regex: {err.msg}")
        if regex_comp.groups == 0:
            regex_comp = re.compile("(" + self.regex + ")")

        if regex_comp.groups != 1:
            if self.name not in regex_comp.groupindex: 
                error(f"if {self.name[0]} contains more than one capture group it must contain a named capture group named {self.name}")
            self.regex_groups = True
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
        if self.format is None:
            if self.xpath is not None or self.regex is not None:
                self.format = "{}"
        else:
            if self.xpath is None and self.regex is None:
                error(f"cannot specify {self.name[0]}f without {self.name[0]}x or {self.name[0]}r")

    def match_xpath(self, src_xml, path, default=[], return_xml_tuple=False):
        if self.xpath is None: return default
        try:
            xpath_matches = src_xml.xpath(self.xpath)
        except lxml.etree.XPathEvalError as ex:
            error(f"aborting! invalid {self.name[0]}x: {str(ex)}: ")
        except Exception as ex:
            error(
                f"aborting! failed to apply {self.name[0]}x to {path}: "
                + f"{ex.__class__.__name__}:  {str(ex)}:"
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
                    except:
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
            if self.regex_groups:
                res.append(RegexMatch(m.group(self.name), list(m.groups()), m.groupdict()))
            else:
                res.append(RegexMatch(m.group(1)))
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
            for m in self.match_regex(x, path, [x]):
                res.append(self.apply_format(m, values, keys))
        return res

class Document:
    def __init__(self, document_type, path, encoding, force_encoding, default_scheme, prefer_parent_scheme, force_scheme):
        self.document_type = document_type
        self.path = path
        self.encoding = encoding
        self.force_encoding = force_encoding
        self.default_scheme = default_scheme
        self.prefer_parent_scheme = prefer_parent_scheme
        self.force_scheme = force_scheme

    def __key(self):
        return (self.document_type, self.path, self.encoding, self.output_enciding)

    def __eq__(x, y):
        return isinstance(y, x.__class__) and x.__key() == y.__key()

    def __hash__(self):
        return hash(self.__key())

class DlContext:
    def __init__(self):
        self.pathes = []

        self.content = Locator("content", ["di", "ci"])
        self.cimin = 1
        self.content_escape_sequence = "<END>"
        self.ci = self.cimin
        self.cimax = float("inf")
        self.ci_continuous = False
        self.content_save_format = ""
        self.content_print_format = ""
        self.content_write_format = ""
        self.content_raw = True
        self.content_input_encoding = "utf-8"
        self.content_forced_input_encoding = False
        self.content_encoding = "utf-8"

        self.label = Locator("label", ["di", "ci"])
        self.label_default_format = None
        self.labels_inside_content = None
        self.label_allow_missing = False

        self.document = Locator("document", ["di", "ci"])
        self.documents_bfs = False
        self.dimin = 1
        self.di = self.dimin
        self.dimax = float("inf")
        self.default_document_encoding = "utf-8"
        self.force_document_encoding = False
        self.default_document_scheme = "https"
        self.prefer_parent_document_scheme = None
        self.force_document_scheme = False

        self.cookie_file = None
        self.cookie_jar = None
        self.selenium_variant = SeleniumVariant.DISABLED
        self.tor_browser_dir = None
        self.selenium_driver = None
        self.selenium_timeout_secs = 10
        self.selenium_poll_frequency_secs = 0.3
        self.selenium_strategy = SeleniumStrategy.FIRST
        self.user_agent_random = False
        self.user_agent = None
        self.locators = [self.content, self.label, self.document]
        self.allow_slashes_in_labels = False
        self.verbosity = Verbosity.WARN
       
        

        self.have_xpath_matching = False
        self.have_label_matching = False
        self.have_content_xpaths = False
        self.have_interactive_matching = False
        self.content_download_required = False
        self.need_content_enc = False


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
    Scan documents for content matches and write these out.

    Matching is a chain of applying an xpath, a regular expression and a python format expression.
    Since xpath and regex can generate multiple results, multiple values may be generated at these steps.
    If a step is not specified, it is skipped.
    The arguments for the format strings are available in the specified order, or as named arguments.

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

    Further Options:
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
    cwd = os.path.dirname(os.path.abspath(__file__))
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
            ctx.tor_browser_dir = "start-tor-browser"
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

def setup(ctx):
    global DEFAULT_CPF
    if len(ctx.pathes) == 0:
        error("must specify at least one url or (r)file")

    ctx.label.setup()
    ctx.content.setup()
    ctx.document.setup()

    if ctx.dimin > ctx.dimax: error(f"dimin can't exceed dimax")
    if ctx.cimin > ctx.cimax: error(f"cimin can't exceed cimax")

    if ctx.cookie_file is not None:
        try:
            ctx.cookie_jar = MozillaCookieJar()
            ctx.cookie_jar.load(ctx.cookie_file, ignore_discard=True,ignore_expires=True)
        except Exception as ex:
            error(f"failed to read cookie file: {str(ex)}")
    if not ctx.content_print_format and not ctx.content_save_format:
        ctx.content_print_format = DEFAULT_CPF
    if ctx.content_write_format and not ctx.content_save_format:
        error(f"cannot specify cwf without csf")

    if not ctx.content_write_format:
        ctx.content_write_format = DEFAULT_CWF

    if ctx.content_print_format:
        ctx.content_print_format = unescape_string(ctx.content_print_format, "cpf")
    if ctx.content_save_format:
        ctx.content_save_format = unescape_string(ctx.content_save_format, "csf")
        ctx.content_write_format = unescape_string(ctx.content_write_format, "cwf")

    if ctx.user_agent is None and ctx.user_agent_random:
        error(f"the options ua and uar are incompatible")
    elif ctx.user_agent_random:
        user_agent_rotator = UserAgent()
        ctx.user_agent = user_agent_rotator.get_random_user_agent()
    elif ctx.user_agent is None and ctx.selenium_variant == SeleniumVariant.DISABLED:
        ctx.user_agent = "dl.py/0.0.1"


    ctx.have_xpath_matching = max([l.xpath is not None for l in ctx.locators])
    ctx.have_label_matching = ctx.label.xpath is not None or ctx.label.regex is not None
    ctx.have_content_xpaths = ctx.labels_inside_content is not None and ctx.label.xpath is not None
    ctx.have_multidocs = ctx.document.xpath is not None or ctx.document.regex is not None or ctx.document.format is not None
    ctx.have_interactive_matching = ctx.label.interactive or ctx.content.interactive

    if not ctx.have_label_matching:
        ctx.label_allow_missing = True
        if ctx.labels_inside_content:
            error(f"cannot specify lic without lx or lr")

    if ctx.label_default_format is None and ctx.label_allow_missing:
        have_ext = False
        form = "dl_"
        # if max was not set it is 'inf' which has length 3 which is a fine default
        didigits = max(len(str(ctx.dimin)), len(str(ctx.dimax)))
        cidigits = max(len(str(ctx.dimin)), len(str(ctx.dimax)))
        if ctx.ci_continuous:
            form += f"{{ci:0{cidigits}}}"
        elif ctx.content.multimatch:
            if ctx.have_multidocs:
                form += f"{{di:0{didigits}}}_{{ci:0{cidigits}}}"
            else:
                form += f"{{ci:0{cidigits}}}"
            
        elif ctx.have_multidocs:
            form += f"{{di:0{didigits}}}"
        
        ctx.label_default_format = form

    ctx.need_content_enc = (
        ctx.need_content_enc 
        or format_string_uses_arg(ctx.content_save_format, 3, "content_enc") 
        or format_string_uses_arg(ctx.content_print_format, 3, "content_enc")
    )
    if not ctx.content_raw:
        if ctx.content_save_format:
            ctx.content_download_required = True
            
        if ctx.content_print_format and not ctx.content_download_required:
            ctx.content_download_required = ctx.need_content_enc or format_string_uses_arg(ctx.content_print_format, 2, "content")

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


def fetch_doc(ctx, doc, raw=False, enc=True, nosingle=False, allowfail=False):
    if doc.document_type in [DocumentType.FILE, DocumentType.RFILE]:
        try:
            with open(doc.path, "rb") as f:
                data = f.read()
            data_enc = str(data, encoding=doc.encoding)
        except Exception as ex:
            if allowfail:
                raise ex
            else:
                error("aborting! failed to read: {str(ex)}")
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
                    except:
                        data_enc = res.text
                else:
                    data_enc = res.text
                    if res.encoding is not None:
                        doc.encoding = res.encoding

            res.close()
            if not data:
                if allowfail:
                    raise Exception(f"failed to download {doc.path}")
                else:
                    error("aborting! failed to download {doc.path}")
    result = []
    if raw: result.append(data)
    if enc: result.append(data_enc)
    if not nosingle and len(result) == 1: return result[0]
    return tuple(result)

def gen_final_content_format(ctx, format, label_txt, di, ci, content_link, content, content_enc, label_regex_match, content_regex_match, doc):
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
    for (text, key, _, _) in Formatter().parse(format):
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
                res += str(val).encode("utf-8")
    return res
  

def normalize_link(ctx, src_doc, link):
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
    if src_doc.force_scheme:
        url_parsed = url_parsed._replace(scheme=src_doc.default_scheme)
    elif url_parsed.scheme == "":
        if src_doc.prefer_parent_scheme and doc_url_parsed and doc_url_parsed.scheme != "":
            scheme = doc_url_parsed.scheme
        else:
            scheme = src_doc.default_scheme    
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
                    f'{context}: accept label "{label}" [Yes/edit/inspect/skip]? ',
                    [(1, yes_indicating_strings), (2, edit_indicating_strings), (3, inspect_indicating_strings), (4, skip_indicating_strings)],
                    1
                )
                if res == 1: break
                if res == 3:
                    print(f'"{doc.path}": content for "{label}":\n' + content_txt)
                    continue
                if res == 4:
                    print("skipping...")
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
                    nosingle=True,
                    allowfail=True
                )
                if res is None:
                    return False
                content_bytes = res[0]
                content_txt = res[1] if ctx.need_content_enc else None
            else:
                content_bytes = None
                content_txt = None
        except Exception as ex:
            sys.stderr.write(f'{document_context}: failed to fetch content from "{content_link}: {str(ex)}"\n')
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
        except:
            error(
                f"{context}: aborting! generated save path is not valid utf-8")
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
        f'"{doc.path}": accept matched document "{matched_path}" [Yes/no/edit]? ',
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
            doc.force_encoding,
            doc.default_scheme,
            doc.prefer_parent_scheme,
            doc.force_scheme
        ) 
        for path in new_paths 
    ]

def dl(ctx):
    docs = deque(ctx.pathes)
    di = ctx.dimin
    ci = ctx.cimin
    handled_content_matches = {}
    handled_document_matches = {}
    while di <= ctx.dimax and docs:
        content_matches_in_doc = False
        document_matches_in_doc = False
        doc = docs.popleft()
        try_number = 0
        final_document_matches = []
        final_content_matches = []
        src = fetch_doc(ctx, doc)
        static_content = (doc.document_type != DocumentType.URL)
        input_timeout = None if static_content else ctx.selenium_poll_frequency_secs
        while True:
            try_number += 1
            same_content = static_content and try_number > 1
            if try_number > 1 and not static_content:
                assert ctx.selenium_variant != SeleniumVariant.DISABLED
                src_new = ctx.selenium_driver.page_source
                same_content = (src_new == src)
                src = src_new

            if not same_content:
                src_xml = lxml.html.fromstring(src) if ctx.have_xpath_matching else None
                content_matches, labels_none_for_n = gen_content_matches(ctx, doc, src, src_xml)
                document_matches = []
                if di <= ctx.dimax:
                    document_matches = gen_document_matches(ctx, doc, src, src_xml)

                if ctx.selenium_strategy == SeleniumStrategy.FIRST:
                    if not content_matches or (not document_matches and di < ctx.dimax):
                        time.sleep(ctx.selenium_poll_frequency_secs)
                        continue
                if ctx.selenium_strategy == SeleniumStrategy.DEDUP:
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
                else:
                    final_content_matches = content_matches
                    final_document_matches = document_matches

            if ctx.selenium_strategy in [SeleniumStrategy.ASK, SeleniumStrategy.DEDUP] and not static_content:
                content_count = len(final_content_matches)
                docs_count = len(final_document_matches)
                msg = ""
                if try_number > 1:
                    msg += "\r"
                msg += f'"{doc.path}": accept {content_count} content'
                if content_count != 1:
                    msg += "s"

                if labels_none_for_n != 0:
                    msg += f" (missing {labels_none_for_n} labels)"
                if ctx.have_multidocs and di <= ctx.dimax:
                    msg += f" and {docs_count} document"
                    if docs_count != 1:
                        msg += "s"
                msg += " [Yes/skip]? "
                rlist = []
                if try_number > 1:
                    rlist, _, _ = select.select([sys.stdin], [], [], input_timeout)
                if not rlist:
                    sys.stdout.write(msg)
                while True:
                    if not rlist:
                        rlist, _, _ = select.select([sys.stdin], [], [], input_timeout)
                    if rlist:
                        accept = parse_prompt_option(sys.stdin.readline(), [(True, yes_indicating_strings), (False, skip_indicating_strings)], True)
                        if accept is None:
                            print("please answer with yes or skip")
                            sys.stdout.write(msg)
                            continue
                        break
                    accept = None
                    break
                if accept:
                    break
            break
        if ctx.ci_continuous:
            ci = ctx.cimin
        for i, cm in enumerate(final_content_matches):
            if not ctx.have_label_matching or cm.label_regex_match is not None:
                content_matches_in_doc = True
                accept = handle_content_match(ctx, doc, cm, di, ci)
                if accept is None:
                    break
                if accept:
                    ci += 1
            else:
                log(ctx, Verbosity.WARN, f"no labels! skipping remaining {len(final_content_matches) - i} content element(s) in document:\n    {doc.path}")
                break
        if not ctx.have_interactive_matching and not content_matches_in_doc:
            log(ctx, Verbosity.WARN, f"no content matches for document: {doc.path}")
        if not ctx.document.interactive and di < ctx.dimax and not document_matches_in_doc and ctx.have_multidocs:
            log(ctx, Verbosity.WARN, f"no document matches for document: {doc.path}")
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

def get_arg(arg):
    return arg[arg.find("=")+1:]

def get_int_arg(arg):
    try:
        return int(get_arg(arg))
    except ValueError:
        error(f"value for {arg} must be an integer")

def get_bool_arg(arg):
    res = parse_bool_string(get_arg(arg))
    if res is None:
        error(f"value in {arg} must be interpretable as a boolean")
    return res

def get_encoding_arg(arg):
    enc = get_arg(arg)
    if not verify_encoding(enc):
        error(f"unknown encoding in '{arg}'")
    return enc

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

def verify_encoding(encoding):
    try:
        "!".encode(encoding=encoding)
        return True
    except:
        return False

def add_doc(ctx, doctype, path):
    prefer_parent_scheme = ctx.prefer_parent_document_scheme
    if prefer_parent_scheme is None:
        prefer_parent_scheme = True
    ctx.pathes.append(
        Document(
            doctype,
            normalize_link(ctx, Document(doctype.url_handling_type(), None, None, False, ctx.default_document_scheme, False, False), path),
            ctx.default_document_encoding,
            ctx.force_document_encoding,
            ctx.default_document_scheme,
            prefer_parent_scheme,
            ctx.force_document_scheme
        )
    )

def main():
    ctx = DlContext()
    if len(sys.argv) < 2:
        error(f"missing command line options. Consider {sys.argv[0]} --help")

    for arg in sys.argv[1:]:
        if arg == "--help" or arg=="-h":
            help()
            return 0

        # content args
        if begins(arg, "cx="):
            ctx.content.xpath = get_arg(arg)
        elif begins(arg, "cr="):
            ctx.content.regex = get_arg(arg)
        elif begins(arg, "cf="):
            ctx.content.format = get_arg(arg)
        elif begins(arg, "cm="):
            ctx.content.multimatch = get_bool_arg(arg)
        elif begins(arg, "cimin="):
            ctx.cimin = get_int_arg(arg)
        elif begins(arg, "cimax="):
            ctx.cimax = get_int_arg(arg)
        elif begins(arg, "cicont="):
            ctx.ci_continuous = get_bool_arg(arg)
        elif begins(arg, "cpf="):
            ctx.content_print_format = get_arg(arg)
        elif begins(arg, "cin="):
            ctx.content.interactive = get_bool_arg(arg)
        elif begins(arg, "csf="):
            ctx.content_save_format = get_arg(arg)
        elif begins(arg, "cwf="):
            ctx.content_write_format = get_arg(arg)
        elif begins(arg, "cl="):
            ctx.content_raw = not get_bool_arg(arg)
        elif begins(arg, "cesc="):
            ctx.content_escape_sequence = get_arg(arg)
        elif begins(arg, "cienc="):
            ctx.content_input_encoding = get_encoding_arg(arg)
        elif begins(arg, "cienc="):
            ctx.content_encoding = get_encoding_arg(arg)
            ctx.content_forced_input_encoding = False
        elif begins(arg, "cenc="):
            ctx.content_encoding = get_encoding_arg(arg)
            ctx.content_forced_input_encoding = True
        # label args
        elif begins(arg, "lx="):
            ctx.label.xpath = get_arg(arg)
        elif begins(arg, "lr="):
            ctx.label.regex = get_arg(arg)
        elif begins(arg, "lf="):
            ctx.label.format = get_arg(arg)
        elif begins("arg", "las="):
            ctx.allow_slashes_in_labels = get_bool_arg(arg)
        elif begins(arg, "ldf="):
            ctx.label_default_format = get_arg(arg)
        elif begins(arg, "lic="):
            ctx.labels_inside_content = get_bool_arg(arg)
        elif begins(arg, "lm="):
            ctx.label.multimatch = get_bool_arg(arg)
        elif begins(arg, "lin="):
            ctx.label.interactive = get_bool_arg(arg)
        elif begins(arg, "lam="):
            ctx.label_allow_missing = get_bool_arg(arg)

        # document args
        elif begins(arg, "dx="):
            ctx.document.xpath = get_arg(arg)
        elif begins(arg, "dr="):
            ctx.document.regex= get_arg(arg)
        elif begins(arg, "df="):
            ctx.document.format = get_arg(arg)
        elif begins(arg, "dimin="):
            ctx.dimin = get_int_arg(arg)
        elif begins(arg, "dimax="):
            ctx.dimax = get_int_arg(arg)
        elif begins(arg, "dm="):
            ctx.document.multimatch = get_bool_arg(arg)
        elif begins(arg, "dbfs="):
            ctx.document_dfs = get_bool_arg(arg)
        elif begins(arg, "ddfs="):
            ctx.document_files = get_bool_arg(arg)
        elif begins(arg, "din="):
            ctx.document.interactive = get_bool_arg(arg)
        elif begins(arg, "denc="):
            ctx.default_document_encoding = get_encoding_arg(arg)
            ctx.force_document_encoding = False
        elif begins(arg, "dfenc="):
            ctx.default_document_encoding = get_encoding_arg(arg)
            ctx.force_document_encoding = True
        elif begins(arg, "dsch="):
            enc = get_arg(arg)
            ctx.default_document_scheme = enc
            ctx.force_document_scheme = False
            if ctx.prefer_parent_document_scheme is None:
                ctx.prefer_parent_document_scheme = False
        elif begins(arg, "dfsch="):
            enc = get_arg(arg)
            ctx.default_document_scheme = enc
            ctx.force_document_scheme = True
        elif begins(arg, "dpsch="):
            ctx.prefer_parent_document_scheme = get_bool_arg(arg)
        # misc args
        elif begins(arg, "url="):
            add_doc(ctx, DocumentType.URL, get_arg(arg))
        elif begins(arg, "file="):
            add_doc(ctx, DocumentType.FILE, get_arg(arg))
        elif begins(arg, "rfile="):
            add_doc(ctx, DocumentType.RFILE, get_arg(arg))
        elif begins(arg, "cookiefile="):
            ctx.cookie_file = get_arg(arg)
        elif begins(arg, "sel="):
            variants_dict = {
                "disabled": SeleniumVariant.DISABLED,
                "tor": SeleniumVariant.TORBROWSER,
                "firefox": SeleniumVariant.FIREFOX,
                "chrome": SeleniumVariant.CHROME
            }
            res = select_variant(get_arg(arg), variants_dict)
            if res is None:
                error(f"no matching selenium variant for '{arg}'")
            ctx.selenium_variant = res
        elif begins(arg, "strat="):
            strats_dict = {
                "first": SeleniumStrategy.FIRST,
                "ask": SeleniumStrategy.ASK,
                "dedup": SeleniumStrategy.DEDUP,
            }
            res = select_variant(get_arg(arg), strats_dict)
            if res is None:
                error(f"no matching selenium strategy for '{arg}'")
            ctx.selenium_strategy = res
        elif begins(arg, "tbdir="):
            ctx.selenium_variant = SeleniumVariant.TORBROWSER
            ctx.tor_browser_dir = get_arg(arg)
        elif begins(arg, "overwrite="):
            ctx.overwrite_files = get_bool_arg(arg)
        elif begins(arg, "ua="):
            ctx.user_agent = get_arg(arg)
        elif begins(arg, "uarandom="):
            ctx.user_agent_random = get_bool_arg(arg)
        elif begins(arg, "v="):
            strats_dict = {
                "info": Verbosity.INFO,
                "warn": Verbosity.WARN,
                "error": Verbosity.ERROR,
            }
            res = select_variant(get_arg(arg), strats_dict)
            if res is None:
                error(f"no matching verbosity level for '{arg}'")
            ctx.verbosity = res
        elif begins(arg, "oenc="):
            ctx.forced_output_encoding = get_encoding_arg(arg)
        elif "":
            continue
        else:
            if "=" not in arg:
                error(f"unrecognized option: '{arg}', are you missing an equals sign?")
            else:
                error(f"unrecognized option: '{arg}'. Consider {sys.argv[0]} --help")
    setup(ctx)
    dl(ctx)
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("error", category=DeprecationWarning) 
    exit(main())
