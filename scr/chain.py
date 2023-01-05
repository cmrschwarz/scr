from scr import context, chain, chain_prototype
import scr.selenium.selenium_context
from scr.transforms import transform
from scr.selenium.selenium_options import SeleniumDownloadStrategy
from typing import Optional


class Chain(chain_prototype.ChainPrototype):
    ctx: 'context.Context'
    parent: Optional['Chain']
    default_text_encoding: str
    prefer_parent_text_encoding: bool
    force_text_encoding: bool

    selenium_context: Optional['scr.selenium.selenium_context.SeleniumContext']
    selenium_download_strategy: SeleniumDownloadStrategy

    transforms: list['transform.Transform']

    subchains: list['chain.Chain']

    def __init__(
        self,
        ctx: 'context.Context',
        parent: Optional['Chain'],
        default_text_encoding: str,
        prefer_parent_text_encoding: bool,
        force_text_encoding: bool,

        selenium_context: Optional['scr.selenium.selenium_context.SeleniumContext'],
        selenium_download_strategy: SeleniumDownloadStrategy,

        transforms: list['transform.Transform'],
    ) -> None:
        self.ctx = ctx
        self.parent = parent
        self.default_text_encoding = default_text_encoding
        self.prefer_parent_text_encoding = prefer_parent_text_encoding
        self.force_text_encoding = force_text_encoding
        self.selelenium_context = selenium_context
        self.selenium_download_strategy = selenium_download_strategy
        self.transforms = transforms

    def set_subchains(self, subchains: list['Chain']) -> None:
        self.subchains = subchains
