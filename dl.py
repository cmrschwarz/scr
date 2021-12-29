#!/usr/bin/env python3
import lxml # pip3 install lxml
import lxml.html
import requests
import sys
import select
import re
import os
from http.cookiejar import MozillaCookieJar
from random_user_agent.user_agent import UserAgent
from tbselenium.tbdriver import TorBrowserDriver
from selenium import webdriver
from selenium.webdriver.common.by import By as SeleniumLookupBy
from collections import deque
from enum import Enum
import time
import datetime

def prefixes(str):
    return [str[:i] for i in range(len(str), 0, -1)]

yes_indicating_strings = prefixes("yes") + prefixes("true") + ["1", "+"]
no_indicating_strings = prefixes("no") + prefixes("false") + ["0", "-"]
skip_indicating_strings = prefixes("skip")
edit_indicating_strings = prefixes("edit")
inspect_indicating_strings = prefixes("inspect")

class DocumentType(Enum):
    URL = 1
    FILE = 2
    RFILE = 3

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

class ContentMatch:
    def __init__(self, label, content):
        self.label = label
        self.content = content

    def __key(self):
        return (self.label, self.content)

    def __eq__(x, y):
        return isinstance(y, x.__class__) and x.__key() == y.__key()

    def __hash__(self):
        return hash(self.__key())

class Locator:
    def __init__(self, name):
        self.name = name
        self.xpath = None
        self.regex = None
        self.format = None
        self.multimatch = False
        self.interactive = False

    def compile_regex(self):
        if self.regex is None:
            return
        try:
            self.regex = re.compile(self.regex)
        except re.error as err:
            error(f"{self.name[0]}r is not a valid regex: {err.msg}")

        if self.regex.groups != 1:
            error(f"{self.name[0]}r  must have exactly one capture group")

    def setup(self):
        self.compile_regex()
        if self.format is None:
            if self.xpath is not None or self.regex is not None:
                self.format = "{}"
        else:
            if self.xpath is None and self.regex is None:
                error(f"cannot specify {self.name[0]}f without {self.name[0]}x or {self.name[0]}r")

    def match_xpath(self, src_xml, path, default=[], return_xml_tuple=False):
        if self.xpath is None: return default
        try:
            res_xpath = src_xml.xpath(self.xpath)
        except lxml.etree.XPathEvalError as ex:
            error(f"aborting! invalid {self.name[0]}x: {ex.msg}: {path}")
        except Exception as ex:
            error(
                f"aborting! failed to apply {self.name[0]}x: "
                + f"{ex.__class__.__name__}: {str(ex)}: {path}"
            )
        if len(res_xpath) > 1 and not self.multimatch:
            res_xpath = res_xpath[:1]
        res = []
        res_xml = []
        for r in res_xpath:
            if type(r) == lxml.etree._ElementUnicodeResult:
                res.append(str(r))
                if return_xml_tuple:
                    try:
                        r = lxml.html.fromstring(res[-1])
                    except:
                        pass
            else:
                res.append(lxml.html.tostring(r, encoding="utf-8"))
            if return_xml_tuple:
                res_xml.append(r)
        if return_xml_tuple:
            return res, res_xml
        return res

    def match_regex(self, val, path, default=[]):
        if self.regex is None or val is None: return default
        if not self.multimatch:
            match = self.regex.match(val)
            if match is None: return []
            return  [match[1]]
        res = []
        for m in self.regex.finditer(val):
            res.append(m.group(1))
        return res

    def apply_format(self, val, values, keys, default=None):
        if self.format is None or val is None: return default
        return self.format.format(
            val,
            [val] + values,
            **dict(
                [(self.name, val)] + [(keys[i], values[i]) for i in range(len(values))]
            )
        )

    def is_unset(self):
        return min([v is None for v in [self.xpath, self.regex, self.format]])

    def apply(self, src, src_xml, path, default=[], values=[], keys=[]):
        if self.is_unset(): return default
        res = []
        for x in self.match_xpath(src_xml, path, [src]):
            for r in self.match_regex(x, path, [x]):
                res.append(self.apply_format(r, values, keys, r))
        return res

class Document:
    def __init__(self, document_type, path):
        self.document_type = document_type
        self.path = path

    def __key(self):
        return (self.document_type, self.path)

    def __eq__(x, y):
        return isinstance(y, x.__class__) and x.__key() == y.__key()

    def __hash__(self):
        return hash(self.__key())

class DlContext:
    def __init__(self):
        self.pathes = []

        self.content = Locator("content")
        self.cimin = 1
        self.ci = self.cimin
        self.cimax = float("inf")
        self.ci_continuous = False
        self.cprint = False

        self.label = Locator("label")
        self.label_default_format = None
        self.labels_inside_content = None

        self.document = Locator("document")
        self.documents_are_files = False
        self.documents_bfs = False
        self.dimin = 1
        self.di = self.dimin
        self.dimax = float("inf")

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

        self.have_xpath_matching = False
        self.have_label_matching = False
        self.have_content_xpaths = False
        self.have_interactive_matching = False

    def is_valid_label(self, label):
        if self.allow_slashes_in_labels: return True
        if "/" in label or "\\" in label: return False
        return True

def error(text):
    sys.stderr.write(text + "\n")
    exit(1)

def help(err=False):
    text = f"""{sys.argv[0]} [OPTIONS]
    Scan documents for content matches and write these out.

    Matching is a chain of applying an xpath, a regular expression and a python format expression.
    Since xpath and regex can generate multiple results, multiple values may be generated at these steps.
    If a step is not specified, it is skipped.
    The arguments for the format strings are available in the specified order, or as named arguments.

    Content to Write out:
        cx=<xpath>           xpath for content matching
        cr=<regex>           regex for content matching
        cf=<format string>   content format string (args: content, di, ci)
        cm=<bool>            allow multiple content matches in one document instead of picking the first
        cimin=<number>       initial content index, each successful match gets one index
        cimax=<number>       max content index, matching stops here
        cicont=<bool>        don't reset the content index for each document
        cprint=<bool>        print found content to stdout
        cin=<bool>           give a prompt to ignore a potential content match

    Labels to give each matched content (becomes the filename):
        lx=<xpath>          xpath for label matching
        lr=<regex>          regex for label matching
        lf=<format string>  label format string (args: label, di, ci)
        lic=<bool>          match for the label within the content instead of the hole document
        las=<bool>          allow slashes in labels
        lm=<bool>           allow multiple label matches in one document instead of picking the first
        lfd=<format string> default label format string to use if there's no match (args: di, ci)
        lin=<bool>          give a prompt to edit the generated label

    Further documents to scan referenced in already found ones:
        dx=<xpath>          xpath for document matching
        dr=<regex>          regex for document matching
        df=<format string>  document format string (args: document)
        dimin=<number>      initial document index, each successful match gets one index
        dimax=<number>      max document index, matching stops here
        dm=<bool>           allow multiple document matches in one document instead of picking the first
        dbfs=<bool>         traverse the matched documents in breadth first order instead of depth first
        din=<bool>          give a prompt to ignore a potential document match

    Initial Documents:
        url=<url>           fetch a document from a url, derived document matches are (relative) urls
        file=<path>         fetch a document from a file, derived documents matches are (relative) file pathes
        rfile=<path>        fetch a document from a file, derived documents matches are urls

    Further Options:
        ua=<string>         user agent to pass in the html header for url GETs
        uar=<bool>          use a rangom user agent
        cookiefile=<path>   path to a netscape cookie file. cookies are passed along for url GETs
        sel=<browser>       use selenium to load urls into an interactive browser session (values: tor,chrome,firefox,disabled)
        strat=<browser>     matching strategy for selenium (values: first, new, interactive)
        tbdir=<path>        root directory of the tor browser installation, implies selenium=tor (default: environment variable TOR_BROWSER_DIR)
        """.strip()
    if err:
        error(text)
    else:
        print(text)

def add_cwd_to_path():
    cwd = os.path.dirname(os.path.abspath(__file__))
    os.environ["PATH"] += ":" + cwd
    return cwd

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

def setup(ctx):
    if len(ctx.pathes) == 0:
        error("must specify at least one url or file")

    [l.setup() for l in ctx.locators]

    if ctx.label.format is None or ctx.label_default_format is None:
        if ctx.label.xpath is None and ctx.label.regex is None:
            form = "dl_"
        else:
            form = "{label}_"
        # if max was not set it is 'inf' which has length 3 which is a fine default
        didigits = max(len(str(ctx.dimin)), len(str(ctx.dimax)))
        cidigits = max(len(str(ctx.dimin)), len(str(ctx.dimax)))
        if ctx.ci_continuous:
            form += f"{{ci:0{cidigits}}}"
        elif ctx.document.multimatch:
            form += f"{{di:0{didigits}}}_{{ci:0{cidigits}}}"
        else:
            form += f"{{di:0{didigits}}}"
        form += "" if ctx.cprint else ".txt"
        if ctx.label.format is None: ctx.label.format = form
        if ctx.label_default_format is None: ctx.label_default_format = form

    if ctx.dimin > ctx.dimax: error(f"dimin can't exceed dimax")
    if ctx.cimin > ctx.cimax: error(f"cimin can't exceed cimax")

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

    if ctx.documents_are_files and ctx.tor:
        error(f"the modes dfiles and tor are incompatible")

    setup_selenium(ctx)

    ctx.have_xpath_matching = max([l.xpath is not None for l in ctx.locators])
    ctx.have_label_matching = ctx.label.xpath is not None or ctx.label.regex is not None
    ctx.have_content_xpaths = ctx.labels_inside_content is not None and ctx.label.xpath is not None
    ctx.have_multidocs = ctx.document.xpath is not None or ctx.document.regex is not None or ctx.document.format is not None
    ctx.have_interactive_matching = ctx.label.interactive or ctx.content.interactive

    if not ctx.have_multidocs:
        ctx.dimax = ctx.dimin
    ctx.di = ctx.dimin
    ctx.ci = ctx.cimin

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


def fetch_doc_source(ctx, doc):
    if doc.document_type in [DocumentType.FILE, DocumentType.RFILE]:
        try:
            with open(doc.path, "r") as f:
                src = f.read()
        except Exception as ex:
            error(f"aborting! failed to read: {str(ex)}")
    else:
        assert doc.document_type == DocumentType.URL
        if ctx.selenium_variant != SeleniumVariant.DISABLED:
            ctx.selenium_driver.get(doc.path)
            src = ctx.selenium_driver.page_source
        else:
            with requests.get(doc.path, cookies=ctx.cookie_jar, headers={'User-Agent': ctx.user_agent}) as response:
                src = response.text
            if not src:
                error(f"aborting! failed to download {doc.path}")
    return src

def handle_content_match(ctx, doc, content, label, di, ci):
    if label is None:
        label = ctx.label_default_format.format([di, ci], di=di, ci=ci)
    else:
        label = ctx.label.format.format([label, di, ci], label=label, di=di, ci=ci)
    if ctx.label.interactive:
        while True:
            if not ctx.is_valid_label(label):
                sys.stderr.write(f'"{doc.path}": labels cannot contain a slash ("{label}")')
            else:
                res = prompt(
                    f'"{doc.path}": accept label "{label}" (Yes/no/inspect/skip)? ',
                    [(1, yes_indicating_strings), (2, no_indicating_strings), (3, inspect_indicating_strings), (4, skip_indicating_strings)],
                    1
                )
                if res == 1: break
                if res == 3:
                    print(f'"{doc.path}": content for "{label}":\n' + content)
                    continue
                if res == 4:
                    print("skipping...")
                    return False
                assert res == 2
            label = input("enter new label: ")

    if ctx.cprint:
        print(f'"{doc.path}": aquired "{label}":\n' + content)
    else:
        if not ctx.is_valid_label(label):
            sys.stderr.write(f"matched label '{label}' would contain a slash, skipping this content from: {doc.path}")
        try:
            f = open(label, "w")
        except Exception as ex:
            error(
                f"aborting! failed to write to file '{label}': {ex.msg}: {doc.path}")
        f.write(content)
        f.close()
        print(f"wrote content into {label} for {doc.path}")
    return True

def handle_document_match(ctx, doc, matched_path):
    if not ctx.document.interactive: return True
    res = prompt(
        f'"{doc.path}": accept matched document "{matched_path}" (Yes/no/edit)? ',
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
    if ctx.have_label_matching and not ctx.labels_inside_content_xpath:
        for lx in ctx.label.match_xpath(src_xml, doc.path, [src]):
            labels.extend(ctx.label.match_regex(src, doc.path, [lx]))
    match_index = 0
    labels_none_for_n = 0
    for content in contents:
        if ctx.labels_inside_content:
            content_xml = contents_xml[match_index] if ctx.have_content_xpaths else None
            labels = []
            for lx in ctx.label.match_xpath(content_xml, doc.path, [src]):
                labels.extend(ctx.label.match_regex(src, doc.path, [lx]))
            if len(label) == 0:
                # will skip the content if there is no label match for it
                # TODO: make this configurable
                continue
            else:
                label = label[0]
        else:
            if not ctx.label.multimatch and len(labels) > 0:
                label = labels[0]
            elif match_index in labels:
                label = labels[match_index]
            elif ctx.label_default_format is not None:
                label = None
            else:
                labels_none_for_n += 1
                label = None
        content_matches.append(ContentMatch(label, content))
        match_index += 1
    return content_matches, labels_none_for_n

def gen_document_matches(ctx, doc, src, src_xml):
    new_paths = ctx.document.apply(src, src_xml, doc.path)
    document_type = doc.document_type
    if document_type == DocumentType.RFILE:
        document_type = DocumentType.URL
    return [ Document(document_type, path) for path in new_paths ]

def dl(ctx):
    docs = deque(ctx.pathes)
    di = ctx.dimin
    ci = ctx.cimin
    handled_content_matches = {}
    handled_document_matches = {}
    while di <= ctx.dimax and docs:
        doc_time_begin = datetime.datetime.now()
        content_matches_in_doc = False
        document_matches_in_doc = False
        doc = docs.popleft()
        try_number = 0
        final_document_matches = []
        final_content_matches = []
        src = fetch_doc_source(ctx, doc)
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

            if ctx.selenium_strategy in [ SeleniumStrategy.ASK, SeleniumStrategy.DEDUP]:
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
                msg += " (Yes/no)? "
                rlist = []
                if try_number > 1:
                    rlist, _, _ = select.select([sys.stdin], [], [], input_timeout)
                if not rlist:
                    sys.stdout.write(msg)
                while True:
                    if not rlist:
                        rlist, _, _ = select.select([sys.stdin], [], [], input_timeout)
                    if rlist:
                        accept = parse_bool_string(sys.stdin.readline(), True, None)
                        if accept is None:
                            print("please answer with yes or no")
                            sys.stdout.write(msg)
                            continue
                        break
                    accept = None
                    break
                if accept:
                    break
        if ctx.ci_continuous:
            ci = ctx.cimin
        for i, cm in enumerate(final_content_matches):
            if not ctx.have_label_matching or cm.label is not None:
                accept = handle_content_match(ctx, doc, cm.content, cm.label, di, ci)
                if accept:
                    content_matches_in_doc = True
                    ci += 1
            else:
                sys.stderr.write(f"no labels! skipping remaining {len(final_content_matches) - i} content element(s) in document:\n    {doc.path}\n")
                break
        if not ctx.have_interactive_matching and not content_matches_in_doc:
            sys.stderr.write(f"no content matches for document: {doc.path}\n")
        if not ctx.document.interactive and di < ctx.dimax and not document_matches_in_doc:
            sys.stderr.write(f"no content matches for document: {doc.path}\n")
        final_document_matches = [d for d in final_document_matches if handle_document_match(ctx, doc, d.path)]
        if ctx.documents_bfs:
            docs.extend(final_document_matches)
        else:
            docs.extendleft(final_document_matches)
        di += 1

    if di <= ctx.dimax and ctx.dimax != float("inf") :
        sys.stderr.write("exiting! all documents handled before dimax was reached\n")


def begins(string, begin):
    return len(string) >= len(begin) and string[0:len(begin)] == begin

def get_arg(arg):
    return arg[arg.find("=")+1:]

def get_int_arg(arg, argname):
    try:
        return int(get_arg(arg))
    except ValueError:
        error(f"value for {argname} must be an integer")

def get_bool_arg(arg, argname):
    res = parse_bool_string(get_arg(arg))
    if res is None:
        error(f"value for {argname} must be interpretable as a boolean")
    return res

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


def main():
    ctx = DlContext()
    # testing, TODO: remove this
    if len(sys.argv) < 2:
        #sys.argv.append('lin=1')
        sys.argv.append("rfile=dl_001.txt")
        sys.argv.append('dx=//span[@class="next-button"]/a/@href')
        sys.argv.append('dimax=3')
        sys.argv.append('ua=ua/0.0.0')
        #sys.argv.append("tbdir=/opt/tor")
        sys.argv.append("sel=f")
        sys.argv.append("strat=dedup")
        sys.argv.append("cin=1")
        sys.argv.append("lin=1")
        sys.argv.append("din=1")
    if len(sys.argv) < 2:
        error(f"missing command line options. Consider {sys.argv[0]} --help")


    for arg in sys.argv[1:]:
        if arg == "--help" or arg=="-h":
            help()
            return 0
        if begins(arg, "cx="):
            ctx.content.xpath = get_arg(arg)
        elif begins(arg, "cr="):
            ctx.content.regex = get_arg(arg)
        elif begins(arg, "cf="):
            ctx.content.format = get_arg(arg)
        elif begins(arg, "cm="):
            ctx.content.multimatch = get_bool_arg(arg, "cm")
        elif begins(arg, "cimin="):
            ctx.cimin = get_int_arg(arg, "cimin")
        elif begins(arg, "cimax="):
            ctx.cimax = get_int_arg(arg, "cimax")
        elif begins(arg, "cicont="):
            ctx.ci_continuous = get_bool_arg(arg, "cicont")
        elif begins(arg, "cprint"):
            ctx.print_ctx = get_bool_arg(arg, "cprint")
        elif begins(arg, "cin"):
            ctx.content.interactive = get_bool_arg(arg, "cin")

        elif begins(arg, "lx="):
            ctx.label.xpath = get_arg(arg)
        elif begins(arg, "lr="):
            ctx.label.regex = get_arg(arg)
        elif begins(arg, "lf="):
            ctx.label.format = get_arg(arg)
        elif begins("arg", "las="):
            ctx.allow_slashes_in_labels = get_bool_arg(arg, "las")
        elif begins(arg, "ldf="):
            ctx.label_default_format = get_arg(arg)
        elif begins(arg, "licx="):
            ctx.labels_inside_content_xpath = get_bool_arg(arg, "licx")
        elif begins(arg, "lm="):
            ctx.label.multimatch = get_bool_arg(arg, "lm")
        elif begins(arg, "lin="):
            ctx.label.interactive = get_bool_arg(arg, "lin")
        elif begins(arg, "dx="):
            ctx.document.xpath = get_arg(arg)
        elif begins(arg, "dr="):
            ctx.document.regex= get_arg(arg)
        elif begins(arg, "df="):
            ctx.document.format = get_arg(arg)
        elif begins(arg, "dimin="):
            ctx.dimin = get_int_arg(arg, "dimin")
        elif begins(arg, "dimax="):
            ctx.dimax = get_int_arg(arg, "dimax")
        elif begins(arg, "dm="):
            ctx.document.multimatch = get_bool_arg(arg, "dm")
        elif begins(arg, "dbfs="):
            ctx.document_dfs = get_bool_arg(arg, "dbfs")
        elif begins(arg, "ddfs="):
            ctx.document_files = get_bool_arg(arg, "dfiles")
        elif begins(arg, "din="):
            ctx.document.interactive = get_bool_arg(arg, "din")

        elif begins(arg, "url="):
            ctx.pathes.append(Document(DocumentType.URL, get_arg(arg)))
        elif begins(arg, "file="):
            ctx.pathes.append(Document(DocumentType.FILE, get_arg(arg)))
        elif begins(arg, "rfile="):
            ctx.pathes.append(Document(DocumentType.RFILE, get_arg(arg)))
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
            ctx.overwrite_files = get_bool_arg(arg, "overwrite")
        elif begins(arg, "ua="):
            ctx.user_agent = get_arg(arg)
        elif begins(arg, "uarandom="):
            ctx.user_agent_random = get_bool_arg(arg, "uarandom")
        else:
            error(f"unrecognized option: '{arg}'. Consider {sys.argv[0]} --help")
    setup(ctx)
    dl(ctx)
    return 0


if __name__ == "__main__":
    exit(main())
