from scr.transforms import transform
from scr.selenium import selenium_options


class Chain:
    default_doc_encoding: str
    prefer_parent_doc_encoding: bool
    force_doc_encoding: bool

    selenium_variant: selenium_options.SeleniumVariant
    selenium_page_acceptance: selenium_options.SeleniumPageAcceptance
    selenium_download_strategy: selenium_options.SeleniumDownloadStrategy

    subchains: list['Chain']
    transforms: list[transform.Transform]
