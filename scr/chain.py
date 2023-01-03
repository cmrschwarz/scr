from scr import context, chain
from scr.transforms import transform
from scr.selenium.selenium_options import SeleniumVariant, SeleniumPageAcceptance, SeleniumDownloadStrategy


class Chain:
    ctx: 'context.Context'
    default_doc_encoding: str
    prefer_parent_doc_encoding: bool
    force_doc_encoding: bool

    selenium_variant: SeleniumVariant
    selenium_page_acceptance: SeleniumPageAcceptance
    selenium_download_strategy: SeleniumDownloadStrategy

    subchains: list['chain.Chain']
    transforms: list['transform.Transform']
