#!/usr/bin/env python3
import lxml # pip3 install lxml
import lxml.html
import requests
from requests.models import Response
import sys
import re
import os
from http.cookiejar import MozillaCookieJar
from random_user_agent.user_agent import UserAgent
from collections import deque
from enum import Enum
class DocumentType(Enum):
    URL = 1
    FILE = 2
    RFILE = 3

class Locator:
    def __init__(self, name):
        self.name = name
        self.format = None
        self.xpath = None
        self.regex = None
        self.multimatch = False

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

    def match_xpath(self, doc_xml, path, default=[], return_xml_tuple=False):
        if self.xpath is None: return default
        try:
            res_xpath = doc_xml.xpath(self.xpath)
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

    def apply(self, doc, doc_xml, path, default=[], values=[], keys=[]):
        if self.is_unset(): return default
        res = []
        for x in self.match_xpath(doc_xml, path, [doc]):
            for r in self.match_regex(x, path, [x]):
                res.append(self.apply_format(r, values, keys, r))
        return res

class DlContext:
    def __init__(self):
        self.pathes = []

        self.content = Locator("content")
        self.cimin = 1
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
        self.dimax = float("inf")

        self.cookie_file = None
        self.cookie_jar = None
        self.tor = False
        self.user_agent_random = False
        self.user_agent = "dl.py/0.0.1"

        self.locators = [self.content, self.label, self.document]

def error(text):
    sys.stderr.write(text + "\n")
    exit(1)


def get_xpath(doc, xpath):
    doc = lxml.html.fromstring(doc)
    element = doc.find("." + xpath)
    return lxml.html.tostring(element)


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
        tor=<bool>          show a tor instance and use that to load urls
        """.strip()
    if err:
        error(text)
    else:
        print(text)

def setup(ctx):
    if len(ctx.pathes) == 0:
        error("must specify at least one url or file")

    [l.setup() for l in ctx.locators]

    if ctx.label.format is None:
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
        ctx.label.format = form

    if ctx.dimin > ctx.dimax: error(f"dimin can't exceed dimax")
    if ctx.cimin > ctx.cimax: error(f"cimin can't exceed cimax")

    if ctx.cookie_file is not None:
        try:
            ctx.cookie_jar = MozillaCookieJar(ctx.cookie_file)
            ctx.cookie_jar.load()
        except Exception as ex:
            error(f"failed to read cookie file: {str(ex)}")


    if ctx.user_agent_random:
        user_agent_rotator = UserAgent()
        ctx.user_agent = user_agent_rotator.get_random_user_agent()

    if ctx.documents_are_files and ctx.tor:
        error(f"the modes dfiles and tor are incompatible")


def dl(ctx):
    have_xpath = max([l.xpath is not None for l in ctx.locators])
    have_label_matching = ctx.label.xpath is not None or ctx.label.regex is not None
    need_content_xpaths = ctx.labels_inside_content is not None and ctx.label.xpath is not None
    di = ctx.dimin
    ci = ctx.cimin
    docs = deque(ctx.pathes)

    while di <= ctx.dimax and docs:
        path, document_type = docs.popleft()
        if document_type in [DocumentType.FILE, DocumentType.RFILE]:
            try:
                with open(path, "r") as f:
                    doc = f.read()
            except:
                error(f"aborting! failed to read {path}")
        else:
            assert document_type == DocumentType.URL
            with requests.get(path, cookies=ctx.cookie_jar, headers={'User-Agent': ctx.user_agent}) as response:
                doc = response.text
            if not doc:
                error(f"aborting! failed to download {path}")
        if have_xpath:
            doc_xml = lxml.html.fromstring(doc)

        if need_content_xpaths:
            contents, contents_xml = ctx.content.match_xpath(doc_xml, path, ([doc], [doc_xml]), True)
        else:
            contents = ctx.content.match_xpath(doc_xml, path, [doc])

        if have_label_matching and not ctx.labels_inside_content_xpath:
            labels = []
            for lx in ctx.label.match_xpath(doc_xml, path, [doc]):
                labels += ctx.label.match_regex(doc, path, [lx])

        if not ctx.ci_continuous:
            ci = ctx.cimin
        i = 0
        progress=False
        for c in contents:
            if ci > ctx.cimax:
                # stopping doc handling since cimax was reached
                # if cicont=1 then this also ends the whole program so we should no longer load documents
                if ctx.ci_continuous:
                    return
                break

            if ctx.labels_inside_content:
                cx = contents_xml[i] if need_content_xpaths else None
                label = ctx.label.apply(c, cx, path, [di, ci], ["di", "ci"])
                if len(label) != 1:
                    # will skip the content
                    label = None
                else:
                    label = label[0]
            else:
                if have_label_matching:
                    if not ctx.label.multimatch and len(labels) > 0:
                        label = labels[0]
                    elif i in labels:
                        label = labels[i]
                        ctx.label.format.format(label, di, ci, label=label, di=di, ci=ci)
                    elif ctx.label_default_format is not None:
                        label = ctx.label_default_format.format(di, ci, di=di, ci=ci)
                    else:
                        sys.stderr.write(f"no labels! skipping remaining {len(contents) - i} content element(s) in document:\n    {path}\n")
                else:
                    label = ctx.label.format.format(di, ci, di=di, ci=ci)
            if label is not None:
                progress = True
                if ctx.cprint:
                    print(f"aquired '{label}' [{path}]:\n" + c)
                else:
                    if "/" in label:
                        sys.stderr.write(f"matched label '{label}' would contain a slash, skipping this content from: {path}")
                    try:
                        f = open(label, "w")
                    except Exception as ex:
                        error(
                            f"aborting! failed to write to file '{label}': {ex.msg}: {path}")
                    f.write(c)
                    f.close()
                    print(f"wrote content into {label} for {path}")
            i += 1
            ci += 1
        if progress == False:
            sys.stderr.write(f"no content matches for document: {path}\n")
        di += 1
        if di <= ctx.dimax:
            new_paths = ctx.document.apply(doc, doc_xml, path)
            if document_type == DocumentType.RFILE:
                document_type = DocumentType.URL
            entries = zip(new_paths, [document_type] * len(new_paths))
            if ctx.documents_bfs:
                docs.extend(entries)
            else:
                docs.extendleft(entries)
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
    try:
        return bool(get_arg(arg))
    except ValueError:
        error(f"value for {argname} must be interpretable as a boolean")


def main():
    ctx = DlContext()
    # testing, TODO: remove this
    if len(sys.argv) < 2:
        sys.argv.append("rfile=./dl_001.txt")
        sys.argv.append('dx=//span[@class="next-button"]/a/@href')
        sys.argv.append('dimax=3')

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

        elif begins(arg, "url"):
            ctx.path.append((get_arg(arg), DocumentType.URL))
        elif begins(arg, "file"):
            ctx.pathes.append((get_arg(arg), DocumentType.FILE))
        elif begins(arg, "rfile"):
            ctx.pathes.append((get_arg(arg), DocumentType.RFILE))
        elif begins(arg, "cookiefile="):
            ctx.cookie_file = get_arg(arg)
        elif begins(arg, "tor="):
            ctx.tor = get_bool_arg(arg, "tor")
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
