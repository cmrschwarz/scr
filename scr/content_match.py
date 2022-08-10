from typing import Optional, Any
from . import locator, match_chain, document
import urllib


class ContentMatch:
    clm: 'locator.LocatorMatch'
    llm: Optional['locator.LocatorMatch'] = None
    mc: 'match_chain.MatchChain'
    doc: 'document.Document'
    filename: Optional[str] = None
    base: Optional['urllib.parse.ParseResult'] = None

    # these are set once we accept the CM, not during it's creation
    ci: Optional[int] = None
    di: Optional[int] = None

    url: Optional[str]
    url_parsed: Optional[urllib.parse.ParseResult] = None

    def __init__(
        self,
        clm: 'locator.LocatorMatch',
        llm: Optional['locator.LocatorMatch'],
        mc: 'match_chain.MatchChain',
        doc: 'document.Document'
    ) -> None:
        self.llm = llm
        self.clm = clm
        self.mc = mc
        self.doc = doc
        self.base = doc.base

    def __key__(self) -> Any:
        return (
            self.doc, self.clm.__key__(),
            self.llm.__key__() if self.llm else None,
        )

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, self.__class__) and other.__key__() == self.__key__()

    def __hash__(self) -> int:
        return hash(self.__key__())
