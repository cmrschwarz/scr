#!/usr/bin/env python3
import lxml.html  # pip3 install lxml
import requests
from requests.models import Response
import sys
import re
import os
from http.cookiejar import MozillaCookieJar


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
                
                --name-xpath <xpath>
                --name-regex <regex>
                --name-format <python formatting string, #1=name, #2=index>
                
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
    if i + 1 == len(sys.argv):
        error(f"missing <{type}> for {arg}")
    return (i+2, sys.argv[i+1])


def compile_regex(regex, arg_name):
    if regex is None:
        return None
    try:
        regex = re.compile(regex)
    except re.error as err:
        error(f"<{arg_name}> is not a valid regex: {err.msg}")

    if regex.groups != 1:
        error(f"<{arg_name}> must have exactly one capture group")

    return regex


def match_xpath_and_regex(doc, doc_xml, xpath, regex, match_kind, default, path):
    if xpath is None and regex is None:
        return default
    res = doc
    if xpath is not None:
        try:
            res = doc_xml.find("." + xpath)
        except (SyntaxError) as ex:
            error(
                f"aborting! invalid {match_kind} xpath: {ex.msg}: {path}")
        except KeyError as ex:
            error(
                f"aborting! invalid {match_kind} xpath: key error on {str(ex)}: {path}")
        except Exception as ex:
            error(
                f"aborting! failed to apply {match_kind} xpath: {ex.__class__.__name__}: {str(ex)}: {path}")
        if not res:
            error(
                f"aborting! failed to match {match_kind} xpath in: {path}")
        res = lxml.html.tostring(res)
    if regex is not None:
        res = regex.match(res)
        if not res:
            error(
                f"aborting! failed to match {match_kind} regex in: {path}")
        res = res[1]
    return res


def dl(path, content_xpath, content_regex, content_format, name_xpath, name_regex,
       name_format, next_xpath, next_regex, next_format, cookie_file, print_results, overwrite, min_index, max_index
    ):
    content_regex = compile_regex(content_regex, "content regex")
    name_regex = compile_regex(name_regex, "name regex")
    next_regex = compile_regex(next_regex, "next regex")
    have_xpath = max([xp is not None for xp in [content_xpath, name_xpath, next_xpath]])
    if next_regex is None and next_xpath is None and next_format is not None:
        error("cannot have next format without next xpath or next regex")
    cookie_jar = None
    if cookie_file is not None:
        try:
            cookie_jar = MozillaCookieJar(cookie_file)
        except Exception as ex:
            error(
                f"aborting! failed to read cookie file from {cookie_file}: {str(ex)}")
    i = min_index
    while (i <= max_index if max_index is not None else True):
        with requests.get(path, cookies=cookie_jar) as response:
            doc = response.text
        if not doc:
            error(f"aborting! failed to download {path}")
        if have_xpath:
            doc_xml = lxml.html.fromstring(doc)

        name = match_xpath_and_regex(
            doc, doc_xml, name_xpath, name_regex, "name", "", path)
        name = name_format.format(name, i, name=name, index=i)

        content = match_xpath_and_regex(
            doc, doc_xml, content_xpath, content_regex, "content", doc, path)

        content_format.format(content, content=content)

        if print_results:
            print(f"aquired '{name}' [{path}]:\n" + content)
        else:
            if "/" in name:
                error(
                    f"aborting! matched name '{name}' would contain a slash: {path}")
            try:
                f = open(name, "wx" if not overwrite else "w")
            except FileExistsError as ex:
                error(
                    f"aborting! target file name '{name}' already exists: {path}")
            except Exception as ex:
                error(
                    f"aborting! failed to write to file '{name}': {ex.msg}: {path}")
            f.write(content)
            f.close()
            print(f"wrote content into {name} for {path}")
        if i != max_index:
            next = match_xpath_and_regex(
                doc, doc_xml, next_xpath, next_regex, "next", None, path)
            if next is None:
                break
            path = next_format.format(next, next=next)
        i++
    print("max index reached")


def main():
    argc = len(sys.argv)
    # if argc < 2:
    #    help(err=True)
    #path = sys.argv[1]
    i = 2
    content_xpath = None
    content_regex = None
    content_format = "{}"
    name_xpath = None
    name_regex = None
    name_format = None
    next_xpath = None
    next_regex = None
    next_format = None
    print_results = False
    cookie_file = None
    overwrite = False
    count = None


# testing!!!!!!!!!!!!!!!
    path = "https://www.fanfiction.net/s/12818664/1/Naruto-Jinch%C5%ABriki-demonio"

    #content_xpath = '//div[@aria-label="story content"]'

    next_xpath = '//select[@title="Chapter Navigation"]/button/@onclick'
    next_regex = "self.location='(.*?)'"
    next_format = "https://www.fanfiction.net/{}"
    cookie_file = "cookies.txt"
    min_index = 1
    max_index = None
    # 1: name
    # 2: index
    overwrite = True

    while i < argc:
        arg = sys.argv[i]
        if arg == "--content-xpath":
            i, content_xpath = get_arg(i, "xpath", arg)
            continue
        if arg == "--content-regex":
            i, content_regex = get_arg(i, "regex", arg)
            continue
        if arg == "--content-format":
            i, content_regex = get_arg(i, "regex", arg)
            continue

        if arg == "--name-xpath":
            i, name_xpath = get_arg(i, "xpath", arg)
            continue
        if arg == "--name-regex":
            i, name_regex = get_arg(i, "regex", arg)
            continue
        if arg == "--name-format":
            i, name_format = get_arg(i, "format", arg)
            continue

        if arg == "--next-xpath":
            i, next_xpath = get_arg(i, "xpath", arg)
            continue
        if arg == "--next-regex":
            i, next_regex = get_arg(i, "regex", arg)
            continue
        if arg == "--next-format":
            i, next_regex = get_arg(i, "format", arg)
            continue

        if arg == "--min-index":
            i, min_index = get_arg(i, "min-index", arg)
            try:
                min_index = int(count)
            except ValueError as ve:
                error(f"supplied <min-index> {min_index} is not a valid integer")
            continue

        if arg == "--max-index":
            i, max_index = get_arg(i, "max-index", arg)
            try:
                max_index = int(max_index)
            except ValueError as ve:
                error(f"supplied <max-index> {max_index} is not a valid integer")
            continue

        if arg == "--cookie-file":
            i, cookie_file = get_arg(i, "cookie file path", arg)
            try:
                count = int(count)
            except ValueError as ve:
                error(f"supplied <count> {count} is not a valid integer")
            continue

        if arg == "--print-results":
            print_results = True
            continue

        if arg == "--overwrite":
            overwrite = True
            continue

    if name_format is None:
        if name_xpath is None and name_regex is None:
            name_format = 'dl_{index:03}.txt'
        else:
            name_format = '{name}_{index:03}.txt'

    dl(path, content_xpath, content_regex, content_format, name_xpath, name_regex,
       name_format, next_xpath, next_regex, next_format, cookie_file, print_results, overwrite, min_index, max_index)
    return 0


if __name__ == "__main__":
    exit(main())
