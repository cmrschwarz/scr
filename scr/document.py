from typing import Optional, Any
from .definitions import (DocumentType)
from . import locator, match_chain, scr_context, utils
import lxml.html
import urllib


class Document:
    document_type: DocumentType
    # since this is used for logging a lot, we put "<content match>"
    # for documents without a path
    path: Optional[str]
    path_parsed: Optional[urllib.parse.ParseResult]
    base: Optional[str]
    base_parsed: Optional[urllib.parse.ParseResult]
    encoding: Optional[str]
    forced_encoding: bool
    text: Optional[str]
    xml: Optional[lxml.html.HtmlElement]
    src_mc: Optional['match_chain.MatchChain']
    locator_match: Optional['locator.LocatorMatch']
    parent_doc: Optional['Document']
    dfmatch: Optional[str]

    def __init__(
        self, document_type: DocumentType,
        path: Optional[str] = None,
        src_mc: Optional['match_chain.MatchChain'] = None,
        parent_doc: Optional['Document'] = None,
        match_chains: Optional[list['match_chain.MatchChain']] = None,
        expand_match_chains_above: Optional[int] = None,
        locator_match: Optional['locator.LocatorMatch'] = None,
        path_parsed: Optional[urllib.parse.ParseResult] = None,
        base: Optional[str] = None,
        base_parsed: Optional[urllib.parse.ParseResult] = None
    ) -> None:
        self.document_type = document_type
        self.path = path
        self.path_parsed = path_parsed
        self.base = base
        self.parent_doc = parent_doc
        self.path_parsed = base_parsed
        self.encoding = None
        self.forced_encoding = False
        self.text = None
        self.xml = None
        self.src_mc = src_mc
        self.locator_match = locator_match
        self.dfmatch = None
        if self.path_parsed is None and self.path is not None:
            self.path_parsed = urllib.parse.urlparse(self.path)
        if not match_chains:
            self.match_chains = []
        else:
            self.match_chains = sorted(
                match_chains,
                key=lambda mc: mc.chain_id
            )
        self.expand_match_chains_above = expand_match_chains_above

    def __key__(self) -> tuple[DocumentType, int,  Optional[str]]:
        return (
            self.document_type,
            self.src_mc.chain_id if self.src_mc else -1,
            self.canonical_url()
        )

    def __eq__(self, other: Any) -> bool:
        return isinstance(self, other.__class__) and self.__key__() == other.__key__()

    def __hash__(self) -> int:
        return hash(self.__key__())

    def decide_encoding(self, ctx: 'scr_context.ScrContext') -> str:
        forced = False
        mc = self.src_mc
        if not mc:
            mc = ctx.match_chains[0]
        if mc.forced_document_encoding:
            enc = mc.forced_document_encoding
            forced = True
        elif self.encoding:
            enc = self.encoding
        else:
            enc = mc.default_document_encoding
        self.encoding = enc
        self.forced_encoding = forced
        return enc

    def canonical_url(self) -> str:
        if self.path_parsed is None:
            # this happens for STRING docs only, so we will have the text
            assert self.text is not None
            return self.text
        return urllib.parse.urlunparse(self.path_parsed)

    def path_for_context(self) -> str:
        if self.path is None:
            return "<document string>"
        else:
            return utils.truncate(self.path)
