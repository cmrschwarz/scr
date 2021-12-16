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
            error(f"<{self.name} regex> is not a valid regex: {err.msg}")

        if self.regex.groups != 1:
            error(f"<{self.name} regex> must have exactly one capture group")

    def setup(self):
        self.compile_regex()
        if self.format is None:
            if self.xpath is not None or self.regex is not None:
                self.format = "{}"
        else:
            if self.xpath is None and self.regex is None:
                error(f"cannot have <{self.name} format> without <{self.name} xpath> or <{self.name} regex>")

    def match_xpath(self, doc_xml, path, default=[]):
        if self.xpath is None: return default
        try:
            res_xpath = doc_xml.xpath(self.xpath)
        except lxml.etree.XPathEvalError as ex:
            error(
                f"aborting! invalid <{self.name} xpath>: {ex.msg}: {path}"
            )
        except Exception as ex:
            error(
                f"aborting! failed to apply <{match_kind} xpath>: " 
                + f"{ex.__class__.__name__}: {str(ex)}: {path}"
            )
        if len(res_xpath) > 1 and not self.multimatch:
            res_xpath = res_xpath[:1]
        res = []
        for r in res_xpath:
            if type(r) == lxml.etree._ElementUnicodeResult:
                res.append(str(r))
            else:
                res.append(lxml.html.tostring(r, encoding="utf-8"))
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

    def apply(self, doc, doc_xml, path, default=None, values=[], keys=[]):
        if self.is_unset(): return default
        res = []
        for x in self.match_xpath(doc_xml, path, [doc]):
            for r in self.match_regex(x, path, [x]):
                res.append(self.apply_format(r, values, keys, r))
        if self.multimatch:
            return res
        else:
            if len(res) == 0: return None
            assert len(res) == 1
            return res[0]
       
       
        


class DlContext:
    def __init__(self):
        self.is_file = False
        self.next_is_file = False
        self.content = Locator("content")
        self.label = Locator("label")
        self.next = Locator("next")
        self.print_results = False
        self.cookie_file = None
        self.cookie_jar = None
        self.overwrite_files = False
        self.count = None
        user_agent_rotator = UserAgent()
        self.user_agent = user_agent_rotator.get_random_user_agent()


def error(text):
    sys.stderr.write(text + "\n")
    exit(1)


def get_xpath(doc, xpath):
    doc = lxml.html.fromstring(doc)
    element = doc.find("." + xpath)
    return lxml.html.tostring(element)


def help(err=False):
    text = f"""
            {sys.argv[0]} <url> [OPTIONS]
                --content-xpath <xpath>
                --content-regex <regex>
                --content-format <python formatting string, #1=content>
                
                --label-xpath <xpath>
                --label-regex <regex>
                --label-format <python formatting string, #1=label, #2=index>
                
                --next-xpath <xpath>
                --next-regex <regex>
                --next-format <python formatting string, #1=next>
                
                --min-index <number>
                --max-index <number>

                --match-multiple
        """.strip()
    if err:
        error(text)
    else:
        print(text)


def get_arg(i, type, arg):
    if (arg[0] == "-"):
        if i + 1 == len(sys.argv):
            error(f"missing <{type}> for {arg}")
        return (i+2, sys.argv[i+1])
    return arg[arg.find("="):]


def dl(ctx):
    locators = [ctx.content, ctx.label, ctx.next]
    [l.setup() for l in locators]

    if ctx.label.format is None:
        if ctx.label.xpath is None and ctx.label.regex is None:
            ctx.label.format = 'dl_{index:03}.txt'
        else:
            ctx.label.format = '{label}_{index:03}.txt'
    have_xpath = max([l.xpath is not None for l in locators])

    path = ctx.path
    is_file = ctx.is_file
  
    if ctx.cookie_file is not None:
        try:
            ctx.cookie_jar = MozillaCookieJar(ctx.cookie_file)
        except Exception as ex:
            error(
                f"aborting! failed to read cookie file from {ctx.cookie_file}: {str(ex)}")
    i = ctx.min_index
    while (i <= ctx.max_index if ctx.max_index is not None else True):
        if is_file:
            try:
                with open(path, "r") as f:
                    doc = f.read()
            except:
                error(f"aborting! failed to read {path}")
        else:
            with requests.get(ctx.path, cookies=ctx.cookie_jar, headers={'User-Agent': ctx.user_agent}) as response:
                doc = response.text
            if not doc:
                error(f"aborting! failed to download {path}")
        if have_xpath:
            doc_xml = lxml.html.fromstring(doc)

        label = ctx.label.apply(doc, doc_xml, path, None, [i], ["index"])

        content = ctx.content.apply(doc, doc_xml, path, doc)

        if ctx.print_results:
            print(f"aquired '{label}' [{path}]:\n" + content)
        else:
            if "/" in label:
                error(
                    f"aborting! matched label '{label}' would contain a slash: {path}")
            try:
                f = open(label, "x" if not ctx.overwrite_files else "w")
            except FileExistsError as ex:
                error(
                    f"aborting! target file label '{label}' already exists: {path}")
            except Exception as ex:
                error(
                    f"aborting! failed to write to file '{label}': {ex.msg}: {path}")
            f.write(content)
            f.close()
            print(f"wrote content into {label} for {path}")
        if i != ctx.max_index:
            path = ctx.next.apply(doc, doc_xml, path)
            if path is None:
                print("aborting! no next page found")
                break
            is_file = ctx.next_is_file
            i += 1
        else:
            print("max index reached")        
    else:
        print("aborting! <max index> is not smaller than <min index>")

def begins(string, begin):
    return len(string) >= len(begin) and string[len(begin)] == begin 

def main():
    ctx = DlContext()
    # testing!!!!!!!!!!!!!!!
    if True:
        ctx.path = "./dl_001.txt"
        ctx.next.xpath = '//span[@class="next-button"]/a/@href'        
        ctx.cookie_file = "cookies.txt"
        ctx.min_index = 1
        ctx.max_index = None
        ctx.is_file = True
        # 1: label
        # 2: index
        ctx.overwrite_files = True
    
    argc = len(sys.argv)
    # if argc < 2:
    #    help(err=True)
    #path = sys.argv[1]

    
    i = 2
    while i < argc:
        arg = sys.argv[i]
        if arg == "--content-xpath" or begins(arg, "cx="):
            i, ctx.content.xpath = get_arg(i, "xpath", arg)
            continue
        if arg == "--content-regex" or begins(arg, "cr="):
            i, ctx.content.regex = get_arg(i, "regex", arg)
            continue
        if arg == "--content-format" or begins(arg, "cf="):
            i, ctx.content.regex = get_arg(i, "regex", arg)
            continue

        if arg == "--label-xpath" or begins(arg, "lx="):
            i, ctx.label.xpath = get_arg(i, "xpath", arg)
            continue
        if arg == "--label-regex" or begins(arg, "lr="):
            i, ctx.label.regex = get_arg(i, "regex", arg)
            continue
        if arg == "--label-format" or begins(arg, "lf="):
            i, ctx.label.format = get_arg(i, "format", arg)
            continue

        if arg == "--next-xpath" or begins(arg, "nx="):
            i, ctx.next.xpath = get_arg(i, "xpath", arg)
            continue
        if arg == "--next-regex" or begins(arg, "nr="):
            i, ctx.next.regex = get_arg(i, "regex", arg)
            continue
        if arg == "--next-format" or begins(arg, "nf="):
            i, ctx.next.format = get_arg(i, "format", arg)
            continue

        if arg == "--min-index" or begins(arg, "imin="):
            i, min_index = get_arg(i, "min-index", arg)
            try:
                ctx.min_index = int(count)
            except ValueError as ve:
                error(f"supplied <min-index> {ctx.min_index} is not a valid integer")
            continue

        if arg == "--max-index" or begins(arg, "imax="):
            i, ctx.max_index = get_arg(i, "max-index", arg)
            try:
                ctx.max_index = int(ctx.max_index)
            except ValueError as ve:
                error(f"supplied <max-index> {ctx.max_index} is not a valid integer")
            continue

        if arg == "--cookie-file" or begins(arg, "cookiefile="):
            i, ctx.cookie_file = get_arg(i, "cookie file path", arg)
            continue

        if arg == "--count" or arg == "-c" or begins(arg, "count="):    
            try:
                count = get_arg(i, "count", arg)
                ctx.count = int(count)
            except ValueError as ve:
                error(f"supplied <count> {ctx.count} is not a valid integer")
            continue

        if arg == "--print":
            ctx.print_results = True
            continue

        if arg == "--overwrite":
            ctx.overwrite_files = True
            continue
    dl(ctx)
    return 0


if __name__ == "__main__":
    exit(main())
