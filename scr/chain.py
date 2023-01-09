from scr import context, chain, chain_prototype, match
from scr.selenium import selenium_context, selenium_options
from scr.transforms import transform, transform_ref
from typing import Any, Optional, cast


class Chain(chain_prototype.ChainPrototype):
    ctx: 'context.Context'
    parent: Optional['Chain']
    default_text_encoding: str
    prefer_parent_text_encoding: bool
    force_text_encoding: bool

    selenium_ctx: Optional['selenium_context.SeleniumContext']
    selenium_download_strategy: 'selenium_options.SeleniumDownloadStrategy'

    transforms: list['transform.Transform']

    subchains: list['chain.Chain']

    aggregation_targets: list['transform_ref.TransformRef']

    def __init__(
        self,
        ctx: 'context.Context',
        parent: Optional['Chain'],
        default_text_encoding: str,
        prefer_parent_text_encoding: bool,
        force_text_encoding: bool,

        selenium_ctx: Optional['selenium_context.SeleniumContext'],
        selenium_download_strategy: 'selenium_options.SeleniumDownloadStrategy',

        transforms: list['transform.Transform'],
    ) -> None:
        self.ctx = ctx
        self.parent = parent
        self.default_text_encoding = default_text_encoding
        self.prefer_parent_text_encoding = prefer_parent_text_encoding
        self.force_text_encoding = force_text_encoding
        self.selenium_ctx = selenium_ctx
        self.selenium_download_strategy = selenium_download_strategy
        self.transforms = transforms
        self.aggregation_targets = []

    def set_subchains(self, subchains: list['Chain']) -> None:
        self.subchains = subchains

    def root(self) -> 'Chain':
        return cast(Chain, super().root())

    def setup(self) -> None:
        for i in range(0, len(self.transforms)):
            self.transforms[i] = self.transforms[i].setup(self, i)
        for sc in self.subchains:
            sc.setup()


class ChainValidationException(Exception):
    cn: 'Chain'

    def __init__(self, cn: 'Chain', *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.cn = cn


def validate_single_chain(cn: Chain) -> None:
    if len(cn.transforms) == 0:
        raise ChainValidationException(cn, f"chain {cn} is unneeded since it has no transforms")

    res = None
    for tf in reversed(cn.transforms):
        res = tf.output_match_types()
        if res is not None:
            break
    out_empty = (res is None or res != set([match.MatchNone]))
    if cn.aggregation_targets and not out_empty:
        raise ChainValidationException(cn, f"output of chain {cn} is unused")


def validate_chain_tree(root_chain: Chain) -> None:
    validate_single_chain(root_chain)
    for sc in root_chain.subchains:
        validate_chain_tree(sc)
