from .definitions import (ScrSetupError, ScrMatchError, Verbosity)
from . import match_chain, scr, utils, document, content_match, selenium_setup
from .config_data_class import ConfigDataClass
from typing import Optional, Union, Any, cast
import lxml.etree
import lxml.html
import re
from selenium.common.exceptions import WebDriverException as SeleniumWebDriverException
from selenium.common.exceptions import JavascriptException as SeleniumJavascriptException
from selenium.webdriver.remote.webdriver import WebDriver as SeleniumWebDriver
from urllib3.exceptions import MaxRetryError as SeleniumMaxRetryError
import textwrap


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

    def parses_documents(self) -> bool:
        return any(x is not None for x in [self.xpath, self.regex, self.js_script])

    def setup_xpath(self, mc: 'match_chain.MatchChain') -> None:
        if self.xpath is None:
            return
        try:
            xp = lxml.etree.XPath(cast(str, self.xpath))
            xp.evaluate(  # type: ignore
                lxml.html.fromstring("<div>test</div>")
            )
        except (lxml.etree.XPathError):
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

    def setup_regex(self, mc: 'match_chain.MatchChain') -> None:
        if self.regex is None:
            return
        try:
            self.regex = re.compile(self.regex, re.DOTALL | re.MULTILINE)
        except re.error as err:
            raise ScrSetupError(
                f"invalid regex ({err.msg}) in {self.get_configuring_argument(['regex'])}"
            )

    def setup_format(self, mc: 'match_chain.MatchChain') -> None:
        if self.format is None:
            return
        scr.validate_format(
            self, ["format"], mc.gen_dummy_content_match(), True, False
        )

    def setup_js(self, mc: 'match_chain.MatchChain') -> None:
        if self.js_script is None:
            return
        args_dict: dict[str, Any] = {}
        dummy_doc = mc.gen_dummy_document()
        scr.apply_general_format_args(dummy_doc, mc, args_dict, ci=None)
        scr.apply_locator_match_format_args(
            self.name, self.gen_dummy_locator_match(), args_dict
        )
        js_prelude = ""
        for i, k in enumerate(args_dict.keys()):
            js_prelude += f"const {k} = arguments[{i}];\n"
        self.js_script = js_prelude + self.js_script

    def setup(self, mc: 'match_chain.MatchChain') -> None:
        self.xpath = utils.empty_string_to_none(cast(str, self.xpath))
        assert self.regex is None or type(self.regex) is str
        self.regex = utils.empty_string_to_none(self.regex)
        self.format = utils.empty_string_to_none(self.format)
        self.setup_xpath(mc)
        self.setup_regex(mc)
        self.setup_js(mc)
        self.setup_format(mc)
        self.validated = True

    def match_xpath(
        self,
        src_text: str,
        src_xml: Optional[lxml.html.HtmlElement],
        doc_path: str,
        store_xml: bool = False
    ) -> list[LocatorMatch]:
        if self.xpath is None:
            lm = LocatorMatch()
            lm.result = src_text
            return [lm]
        assert src_xml is not None
        try:
            xp = cast(lxml.etree.XPath, self.xpath)
            if type(src_xml) == lxml.etree._ElementUnicodeResult:  # type: ignore
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
                xpath_matches = (xp.evaluate(src_xml))  # type: ignore
        except lxml.etree.XPathError:
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
            if type(xm) == lxml.etree._ElementUnicodeResult:  # type: ignore
                lm.xmatch = str(xm)
                if store_xml:
                    lm.xmatch_xml = xm
            else:
                try:
                    lm.result = lxml.html.tostring(xm, encoding="unicode")
                    lm.xmatch = lm.result
                    if store_xml:
                        lm.xmatch_xml = xm
                except (lxml.etree.LxmlError, UnicodeEncodeError) as ex1:
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
        self, doc: 'document.Document', mc: 'match_chain.MatchChain', lms: list['LocatorMatch'],
        multimatch: Optional[bool] = None
    ) -> list['LocatorMatch']:
        if self.js_script is None:
            return lms
        if multimatch is None:
            multimatch = self.multimatch
        lms_new: list[LocatorMatch] = []
        for lm in lms:
            args_dict: dict[str, Any] = {}
            scr.apply_general_format_args(doc, mc, args_dict, ci=None)
            scr.apply_locator_match_format_args(self.name, lm, args_dict)
            try:
                mc.js_executed = True
                drv = cast(SeleniumWebDriver, mc.ctx.selenium_driver)

                results = drv.execute_script(
                    self.js_script, *args_dict.values())  # type: ignore

            except SeleniumJavascriptException as ex:
                arg = cast(str, self.get_configuring_argument(['js_script']))
                name = arg[0: arg.find("=")]
                scr.log(
                    mc.ctx, Verbosity.WARN,
                    f"{name}: js exception on {utils.truncate(doc.path)}:\n{textwrap.indent(str(ex), '    ')}"
                )
                continue
            except (SeleniumWebDriverException, SeleniumMaxRetryError):
                if selenium_setup.selenium_has_died(mc.ctx):
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
        self, cm: 'content_match.ContentMatch', lm: LocatorMatch
    ) -> None:
        if not self.format:
            return
        lm.fres = self.format.format(**scr.content_match_build_format_args(cm))
        lm.result = lm.fres

    def apply_format_for_document_match(
        self, doc: 'document.Document', mc: 'match_chain.MatchChain', lm: 'LocatorMatch'
    ) -> None:
        if not self.format:
            return
        args_dict: dict[str, Any] = {}
        scr.apply_general_format_args(doc, mc, args_dict, ci=None)
        scr.apply_locator_match_format_args(self.name, lm, args_dict)
        lm.fres = self.format.format(**args_dict)
        lm.result = lm.fres

    def is_unset(self) -> bool:
        return min([v is None for v in [self.xpath, self.regex, self.format]])
