from .document import Document
from .match_chain import MatchChain
from .config_data_class import ConfigDataClass
from .match_steps.match_step import MatchStep

from typing import Optional, Any
import lxml.etree
import lxml.html
import copy


class LocatorMatch:
    doc: Optional[Document]
    text: str
    xml: Optional[lxml.html.HtmlElement]
    match_args: dict[str, str]
    slots = tuple(__annotations__.keys())

    def __init__(self, doc: Optional[Document], text: str, xml: Optional[lxml.html.HtmlElement] = None):
        self.doc = doc
        self.text = text
        self.xml = xml
        self.match_args = {}

    def __key__(self) -> tuple[Optional[str], Optional[lxml.html.HtmlElement], dict[str, str]]:
        return (self.text, self.xml, self.match_args)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, self.__class__) and self.__key__() == other.__key__()

    def __hash__(self) -> int:
        return hash(self.__key__())

    def copy(self) -> 'LocatorMatch':
        return copy.copy(self)


class Locator(ConfigDataClass):
    name: str
    xpath_sibling_match_depth: int = 0
    interactive: bool

    __annotations__: dict[str, type]

    _config_slots_: list[str] = (
        ConfigDataClass._annotations_as_config_slots(
            __annotations__, []
        )
    )
    mc: MatchChain  # initialized on setup
    match_steps: list[MatchStep]
    first_order_dependant_step: int
    last_xpath_needing_step: Optional[int] = None
    last_xml_needing_step: Optional[int] = None
    multimatch: bool = False
    # steps that can be executed before interactive selenium deduplication

    def __init__(self, name: str, blank: bool = False) -> None:
        super().__init__(blank)
        self.name = name
        self.match_steps = []

    def is_active(self) -> bool:
        return len(self.match_steps) != 0

    def needs_document_content(self) -> bool:
        return len(self.match_steps) != 0

    def needs_filename(self) -> bool:
        return any(ms.needs_filename() for ms in self.match_steps)

    def is_order_dependant(self) -> bool:
        return self.first_order_dependant_step < len(self.match_steps)

    def gen_dummy_locator_match(self) -> LocatorMatch:
        lm = LocatorMatch(None, "")
        for ms in self.match_steps:
            ms.apply_to_dummy_locator_match(lm)
        return lm

    def setup(self, mc: 'MatchChain') -> None:
        self.mc = mc
        found_order_dependant_step = False
        self.first_order_dependant_step = len(self.match_steps)
        for i in range(len(self.match_steps)):
            ms = self.match_steps[i]
            ms.setup(self, self.match_steps[i - 1] if i > 0 else None)
            if not found_order_dependant_step:
                if ms.is_order_dependent():
                    self.first_order_dependant_step = i
            if ms.needs_xml():
                self.last_xml_needing_step = i
            if ms.needs_xpath():
                self.last_xpath_needing_step = i
            if not self.multimatch and ms.has_multimatch():
                self.multimatch = True

    def apply_order_independant_steps(self, doc: Document, text: str, xml: Optional[lxml.html.HtmlElement]) -> list[LocatorMatch]:
        matches = [LocatorMatch(doc, text, xml)]
        for ms in self.match_steps[0:self.first_order_dependant_step]:
            matches = ms.apply(matches)
        return matches

    def apply_order_dependant_steps(self, match: LocatorMatch) -> LocatorMatch:
        result = [match]
        for ms in self.match_steps[self.first_order_dependant_step:]:
            result = ms.apply(result)
        assert len(result) == 1
        return result[0]
