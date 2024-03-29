from typing import Optional, Union
from .definitions import (
    SeleniumStrategy, SeleniumDownloadStrategy, DocumentType, DocumentDuplication,
    DEFAULT_ESCAPE_SEQUENCE, FALLBACK_DOCUMENT_SCHEME)
from .config_data_class import ConfigDataClass
from . import locator, content_match, scr_context, document
import urllib.parse


class MatchChain(ConfigDataClass):
    # config members
    # this is a config member so it is copied on apply_defaults
    ctx: 'scr_context.ScrContext'
    content_escape_sequence: str = DEFAULT_ESCAPE_SEQUENCE
    cimin: int = 1
    cimax: Union[int, float] = float("inf")
    ci_continuous: bool = False
    document_duplication: DocumentDuplication = DocumentDuplication.UNIQUE
    content_save_format: Optional[str] = None
    content_print_format: Optional[str] = None
    content_write_format: Optional[str] = None
    content_shell_command_format: Optional[str] = None
    content_shell_command_stdin_format: Optional[str] = None
    content_shell_command_print_output: bool = False
    content_forward_format: Optional[str] = None
    content_forward_chains: list['MatchChain']
    content_raw: bool = True

    content_input_encoding: str = "utf-8"
    content_force_input_encoding: bool = False
    save_path_interactive: bool = False

    label_default_format: Optional[str] = None
    filename_default_format: Optional[str] = None
    labels_inside_content: bool = False
    label_allow_missing: bool = False
    allow_slashes_in_labels: bool = False
    overwrite_files: bool = True

    dimin: int = 1
    dimax: Union[int, float] = float("inf")
    default_document_encoding: str = "utf-8"
    force_document_encoding: bool = False

    default_document_scheme: str = FALLBACK_DOCUMENT_SCHEME
    prefer_parent_document_scheme: bool = False
    force_document_scheme: bool = False

    selenium_strategy: SeleniumStrategy = SeleniumStrategy.PLAIN
    selenium_download_strategy: SeleniumDownloadStrategy = SeleniumDownloadStrategy.EXTERNAL

    document_output_chains: list['MatchChain']

    file_base: Optional[Union['urllib.parse.ParseResult', str]] = None
    url_base: Optional[Union['urllib.parse.ParseResult', str]] = None
    force_mc_base: bool = False

    __annotations__: dict[str, type]
    _config_slots_: list[str] = (
        ConfigDataClass._annotations_as_config_slots(
            __annotations__, [])
    )

    # subconfig members
    loc_content: 'locator.Locator'
    loc_label: 'locator.Locator'
    loc_document: 'locator.Locator'

    _subconfig_slots_ = ['loc_content', 'loc_label', 'loc_document']

    # non config members
    chain_id: int
    di: int
    ci: int
    js_executed: bool = False
    has_xpath_matching: bool = False
    has_label_matching: bool = False
    has_content_xpaths: bool = False
    # TODO: this should include if this is the target of any doc=...
    has_document_matching: bool = False
    has_content_matching: bool = False
    has_interactive_matching: bool = False
    need_content: bool = False
    need_label: bool = False
    need_filename: bool = False
    need_filename_for_interaction: bool = False
    need_output_multipass: bool = False
    content_matches: list['content_match.ContentMatch']
    document_matches: list['document.Document']
    handled_content_matches: set['content_match.ContentMatch']
    handled_document_matches: set['document.Document']
    requested_document_urls: set[str]
    satisfied: bool = True
    labels_none_for_n: int = 0

    def __init__(self, ctx: 'scr_context.ScrContext', chain_id: int, blank: bool = False) -> None:
        super().__init__(blank)

        self.ctx = ctx
        self.chain_id = chain_id
        # we can't put [self] as a default here because that would be propagated
        # as a default to other chains
        self.document_output_chains = []

        self.content_forward_chains = []

        self.loc_content = locator.Locator("content", blank)
        self.loc_label = locator.Locator("label", blank)
        self.loc_document = locator.Locator("document", blank)

        self.content_matches = []
        self.document_matches = []
        self.handled_content_matches = set()
        self.handled_document_matches = set()
        self.requested_document_urls = set()

    def gen_dummy_document(self) -> 'document.Document':
        d = document.Document(
            DocumentType.FILE, "",
            locator_match=self.loc_document.gen_dummy_locator_match()
        )
        d.encoding = ""
        return d

    def gen_dummy_content_match(self, has_filename: bool) -> 'content_match.ContentMatch':
        clm = self.loc_content.gen_dummy_locator_match()
        if self.has_label_matching:
            llm = self.loc_label.gen_dummy_locator_match()
        elif self.label_default_format:
            llm = locator.LocatorMatch()
            llm.fres = ""
        else:
            llm = None

        dcm = content_match.ContentMatch(
            clm, llm, self, self.gen_dummy_document())
        if self.loc_content.multimatch:
            dcm.ci = 0
        if self.has_document_matching:
            dcm.di = 0
        dcm.filename = "" if has_filename else None
        return dcm

    def accepts_content_matches(self) -> bool:
        return self.di <= self.dimax

    def need_document_matches(self, current_di_used: int) -> bool:
        return (
            self.has_document_matching
            and self.di <= (self.dimax - (1 if current_di_used else 0))
        )

    def need_content_matches(self) -> bool:
        assert self.ci is not None
        assert self.di is not None
        return self.has_content_matching and self.ci <= self.cimax and self.di <= self.dimax

    def is_valid_label(self, label: str) -> bool:
        if self.allow_slashes_in_labels:
            return True
        if "/" in label or "\\" in label:
            return False
        return True
