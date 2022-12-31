from .definitions import SeleniumStrategy, SeleniumDownloadStrategy, FALLBACK_DOCUMENT_SCHEME, DEFAULT_DOC_ENCODING
from .match_steps.match_step import MatchStep
import copy
class Chain:
    index: int
    parent: Option['Chain']
    subchains: list['Chain']
    subchain_template: 'Chain'
    match_steps: list[MatchStep]

    selenium_strategy: SeleniumStrategy = SeleniumStrategy.PLAIN
    selenium_download_strategy: SeleniumDownloadStrategy = SeleniumDownloadStrategy.EXTERNAL

    default_document_encoding: str = DEFAULT_DOCUMENT_ENCODING
    prefer_parent_document_encoding: bool = False
    force_document_encoding: bool = False

    default_document_scheme: str = FALLBACK_DOCUMENT_SCHEME
    prefer_parent_document_scheme: bool = False
    force_document_scheme: bool = False

    default_document_file_base: Optional[Union['urllib.parse.ParseResult', str]] = None
    prefer_parent_file_base: bool = False

    default_document_url_base: Optional[Union['urllib.parse.ParseResult', str]] = None
    prefer_parent_url_base: bool = False

    def __init__(self):
        pass

    def clone(self, new_index: int) -> 'Chain':
        cp = copy.deepcopy(self)
        cp.index = new_index
