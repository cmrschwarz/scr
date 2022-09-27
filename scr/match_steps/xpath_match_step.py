from .match_step import MatchStep
from ..locator import Locator, LocatorMatch
from ..definitions import ScrSetupError, ScrMatchError
from ..utils import not_none
from typing import cast, Optional, Any, OrderedDict
import lxml.etree
import lxml.html


def eval_xpath(xpath: lxml.etree.XPath, src_xml: lxml.html.HtmlElement) -> Any:
    if type(src_xml) == lxml.etree._ElementUnicodeResult:  # type: ignore
        # since lxml doesn't allow us to evaluate xpaths on these,
        # but we need it e.g. for lic, we hack in support for it by
        # generating a derived xpath that gets the expected results while
        # actually being evaluated on the parent
        if src_xml.attrname is None:
            fixed_xpath = "./text()"
        else:
            fixed_xpath = f"./@{src_xml.attrname}"

        if xpath.path[0:1] != "/":
            fixed_xpath += "/"
        fixed_xpath += xpath.path
        return src_xml.getparent().xpath(fixed_xpath)
    else:
        return xpath.evaluate(src_xml)  # type: ignore


def build_sibling_xpath(root: lxml.html.HtmlElement, elem: lxml.html.HtmlElement, sibling_depth: int) -> lxml.etree.XPath:
    res = ""
    level = 0
    if type(elem) == lxml.etree._ElementUnicodeResult:  # type: ignore
        if elem.attrname is None:
            res = "/text()"
        else:
            res = f"/@{elem.attrname}"
        elem = elem.getparent()
    while True:
        parent = cast(Optional[lxml.html.HtmlElement], elem.getparent())
        if level >= sibling_depth:
            index = 1
            if parent is not None:
                for e in parent.iterchildren():
                    if e == elem:
                        break
                    if e.tag == elem.tag:
                        index += 1
            res = f"/{elem.tag}[{index}]{res}"
        else:
            res = f"/{elem.tag}{res}"
            level += 1
        if elem == root:
            break
        assert parent is not None
        elem = parent
    return lxml.etree.XPath(res)


def match_siblings(xpath_matches: list[lxml.html.HtmlElement], src_xml: lxml.html.HtmlElement, sibling_depth: int) -> list[lxml.html.HtmlElement]:
    if sibling_depth == 0:
        return xpath_matches
    # we deduplicate based on the match and it's parent, because
    # non identical unicode results with the same text will otherwise
    # be merged
    matches: OrderedDict[tuple[lxml.html.HtmlElement, lxml.html.HtmlElement], None] = OrderedDict()
    for xm in xpath_matches:
        # the sibling xpath will match the original element aswell,
        # so no need to add it manually
        sibling_xpath = build_sibling_xpath(src_xml, xm, sibling_depth)
        sibling_matches = eval_xpath(sibling_xpath, src_xml)
        if not isinstance(sibling_matches, list):
            continue

        for match in sibling_matches:
            matches[(match.getparent(), match)] = None
    return [k[1] for k in matches.keys()]


class XPathMatchStep(MatchStep):
    multimatch: bool = True
    xpath_sibling_match_depth: int = 0

    _config_slots_: list[str] = (
        MatchStep._annotations_as_config_slots(__annotations__, [])
    )
    xpath: lxml.etree.XPath
    store_xml: bool
    step_type_occurence_count: int

    def __init__(self, index: int, name: str, step_type_occurence_count: int, arg: str, arg_val: str) -> None:
        super().__init__(index, name, step_type_occurence_count, arg, arg_val)

    def setup(self, loc: 'Locator', prev: Optional['MatchStep']) -> None:
        try:
            xp = lxml.etree.XPath(self.arg_val)
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

    def apply(self, lms: list[LocatorMatch]) -> list[LocatorMatch]:
        err = False
        res = []
        for lm in lms:
            src_xml = not_none(lm.xml)
            try:
                xpath_matches = eval_xpath(self.xpath, src_xml)
            except (lxml.etree.XPathError, lxml.etree.LxmlError):
                err = True
            if err or not isinstance(xpath_matches, list):
                raise ScrMatchError(
                    f"xpath matching failed for: {self.get_configuring_argument(['xpath'])}"
                )

            if len(xpath_matches) > 1 and not self.multimatch:
                xpath_matches = xpath_matches[:1]
            else:
                xpath_matches = match_siblings(xpath_matches, src_xml, self.xpath_sibling_match_depth)

            for xm in xpath_matches:
                lm = LocatorMatch()
                if type(xm) == lxml.etree._ElementUnicodeResult:  # type: ignore
                    lm.text = str(xm)
                    if self.store_xml:
                        lm.xml = xm
                else:
                    try:
                        lm.text = lxml.html.tostring(xm, encoding="unicode").strip()
                        if self.store_xml:
                            lm.xml = xm
                    except (lxml.etree.LxmlError, UnicodeEncodeError):
                        raise ScrMatchError(
                            f"xpath match encoding in  {self.get_configuring_argument(['xpath'])} failed"
                        )
                res.append(lm)
        return res

    def needs_xml(self) -> bool:
        return True

    def needs_xpath(self) -> bool:
        return True

    def has_multimatch(self) -> bool:
        return self.multimatch
