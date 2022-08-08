from .definitions import SeleniumVariant, Verbosity, DEFAULT_TIMEOUT_SECONDS
from . import match_chain, download_job, document
from .config_data_class import ConfigDataClass
from typing import Optional, Any
import multiprocessing
import os
from http.cookiejar import MozillaCookieJar
from selenium.webdriver.remote.webdriver import WebDriver as SeleniumWebDriver
from collections import deque


class ScrContext(ConfigDataClass):
    # config members
    cookie_file: Optional[str] = None
    exit: bool = False
    selenium_variant: SeleniumVariant = SeleniumVariant.DISABLED
    selenium_headless: bool = False
    tor_browser_dir: Optional[str] = None
    user_agent_random: Optional[bool] = False
    user_agent: Optional[str] = None
    verbosity: Verbosity = Verbosity.WARN
    documents_bfs: bool = False
    selenium_keep_alive: bool = False
    repl: bool = False
    request_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_download_threads: int = multiprocessing.cpu_count()

    selenium_log_path: str = os.devnull
    selenium_poll_frequency_secs: float = 0.3
    selenium_content_count_pad_length: int = 6
    downloads_temp_dir: Optional[str] = None
    download_tmp_index: int = 0

    # not really config, but recycled in repl mode
    dl_manager: Optional['download_job.DownloadManager'] = None
    cookie_jar: Optional[MozillaCookieJar] = None
    cookie_dict: dict[str, dict[str, dict[str, Any]]]
    selenium_driver: Optional[SeleniumWebDriver] = None
    stdin_text: Optional[str] = None
    __annotations__: dict[str, type]
    _config_slots_: list[str] = (
        ConfigDataClass._previous_annotations_as_config_slots(
            __annotations__, []
        )
    )

    # non config members
    match_chains: list['match_chain.MatchChain']
    docs: deque['document.Document']
    reused_doc: Optional['document.Document'] = None
    changed_selenium: bool = False
    defaults_mc: 'match_chain.MatchChain'
    origin_mc: 'match_chain.MatchChain'
    error_code: int = 0
    abort: bool = False

    # used for --help --version and selinstall/selupdate to indicate
    # that if there are no match chains etc. we should exit without error
    special_args_occured: bool = False

    def __init__(self, blank: bool = False) -> None:
        super().__init__(blank)
        self.cookie_dict = {}
        self.match_chains = []
        self.docs = deque()
        self.defaults_mc = match_chain.MatchChain(self, -1)
        self.origin_mc = match_chain.MatchChain(self, -1, blank=True)
        # turn ctx to none temporarily for origin so it can be deepcopied
        self.origin_mc.ctx = None  # type: ignore
