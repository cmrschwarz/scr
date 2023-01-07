from typing import Optional, cast
from scr.transforms import transform
from scr.selenium import selenium_options, selenium_context
from scr.scr_option import ScrOption
from scr import chain, context, chain_prototype


class ChainOptions(chain_prototype.ChainPrototype):
    default_text_encoding: ScrOption[str]
    prefer_parent_text_encoding: ScrOption[bool]
    force_text_encoding: ScrOption[bool]

    selenium_variant: ScrOption['selenium_options.SeleniumVariant']
    selenium_download_strategy: ScrOption['selenium_options.SeleniumDownloadStrategy']

    subchains: list['ChainOptions']
    transforms: list['transform.Transform']

    cha: ScrOption['selenium_options.SeleniumVariant']

    parent: Optional['ChainOptions']

    def __init__(
        self,
        default_text_encoding: Optional[str] = None,
        prefer_parent_text_encoding: Optional[bool] = None,
        force_text_encoding: Optional[bool] = None,

        selenium_variant: Optional['selenium_options.SeleniumVariant'] = None,
        selenium_download_strategy: Optional['selenium_options.SeleniumDownloadStrategy'] = None,

        subchains: Optional[list['ChainOptions']] = None,
        transforms: Optional[list['transform.Transform']] = None,
        parent: Optional['ChainOptions'] = None
    ) -> None:
        self.default_text_encoding = ScrOption(default_text_encoding)
        self.prefer_parent_text_encoding = ScrOption(prefer_parent_text_encoding)
        self.force_text_encoding = ScrOption(force_text_encoding)
        self.selenium_variant = ScrOption(selenium_variant)
        self.selenium_download_strategy = ScrOption(selenium_download_strategy)
        self.parent = parent
        self.subchains = subchains if subchains is not None else []
        for sc in self.subchains:
            sc.parent = self
        self.transforms = transforms if transforms is not None else []

    def root(self) -> 'ChainOptions':
        return cast(ChainOptions, super().root())


DEFAULT_CHAIN_OPTIONS = ChainOptions(
    default_text_encoding="utf-8",
    prefer_parent_text_encoding=False,
    force_text_encoding=False,
    selenium_variant=selenium_options.SeleniumVariant.DISABLED,
    selenium_download_strategy=selenium_options.SeleniumDownloadStrategy.SCR
)


def get_selenium_context(co: ChainOptions, parent: Optional['chain.Chain']) -> Optional['selenium_context.SeleniumContext']:
    if co.selenium_variant.is_set():
        sv = co.selenium_variant.get()
        if (
            parent is not None
            and parent.selenium_ctx is not None
            and parent.selenium_ctx.variant == sv
        ):
            return parent.selenium_ctx
    else:
        if parent is not None:
            return parent.selenium_ctx
        else:
            sv = DEFAULT_CHAIN_OPTIONS.selenium_variant.get()
    if sv == selenium_options.SeleniumVariant.DISABLED:
        return None
    return selenium_context.SeleniumContext(sv)


def create_subchain(co: ChainOptions, ctx: 'context.Context', parent: 'chain.Chain') -> 'chain.Chain':
    c = chain.Chain(
        ctx, parent,
        co.default_text_encoding.get_or_default(parent.default_text_encoding),
        co.prefer_parent_text_encoding.get_or_default(parent.prefer_parent_text_encoding),
        co.force_text_encoding.get_or_default(parent.force_text_encoding),
        get_selenium_context(co, parent),
        co.selenium_download_strategy.get_or_default(parent.selenium_download_strategy),
        co.transforms
    )
    subchains: list[chain.Chain] = []
    for sc in co.subchains:
        subchains.append(create_subchain(sc, ctx, c))
    c.set_subchains(subchains)
    return c


def create_root_chain(co: ChainOptions, ctx: 'context.Context') -> 'chain.Chain':
    sv = co.selenium_variant.get_or_default(DEFAULT_CHAIN_OPTIONS.selenium_variant.get())
    if sv == selenium_options.SeleniumVariant.DISABLED:
        sel_ctx = None
    else:
        sel_ctx = selenium_context.SeleniumContext(sv)

    c = chain.Chain(
        ctx, None,
        co.default_text_encoding.get_or_default(DEFAULT_CHAIN_OPTIONS.default_text_encoding.get()),
        co.prefer_parent_text_encoding.get_or_default(DEFAULT_CHAIN_OPTIONS.prefer_parent_text_encoding.get()),
        co.force_text_encoding.get_or_default(DEFAULT_CHAIN_OPTIONS.force_text_encoding.get()),
        sel_ctx,
        co.selenium_download_strategy.get_or_default(DEFAULT_CHAIN_OPTIONS.selenium_download_strategy.get()),
        co.transforms
    )
    subchains: list[chain.Chain] = []
    for sc in co.subchains:
        subchains.append(create_subchain(sc, ctx, c))
    c.set_subchains(subchains)
    return c


def update_chain(c: 'chain.Chain', co: ChainOptions) -> None:
    c.default_text_encoding = co.default_text_encoding.get_or_default(c.default_text_encoding)
    c.prefer_parent_text_encoding = co.prefer_parent_text_encoding.get_or_default(c.prefer_parent_text_encoding)
    c.force_text_encoding = co.force_text_encoding.get_or_default(c.force_text_encoding)

    curr_sc = c.selenium_ctx
    if curr_sc is not None:
        sv = co.selenium_variant.get_or_default(DEFAULT_CHAIN_OPTIONS.selenium_variant.get())
        if curr_sc.variant != sv:
            if c.parent is None or c.parent.selenium_ctx is not curr_sc:
                curr_sc.destroy()
            c.selenium_ctx = get_selenium_context(co, c.parent)
    else:
        c.selenium_ctx = get_selenium_context(co, c.parent)

    c.selenium_download_strategy = co.selenium_download_strategy.get_or_default(c.selenium_download_strategy)
    c.transforms = co.transforms

    retained_chain_count = min(len(c.subchains), len(co.subchains))
    for i in range(0, retained_chain_count):
        update_chain(c.subchains[i], co.subchains[i])

    c.subchains = c.subchains[:retained_chain_count]

    for i in range(retained_chain_count, len(co.subchains)):
        c.subchains.append(create_subchain(co.subchains[i], c.ctx, c))
