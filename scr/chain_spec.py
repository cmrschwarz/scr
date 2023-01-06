
from typing import Iterable, Optional
from abc import ABC, abstractmethod
from scr import chain, range_spec, chain_options, chain_prototype


class ChainSpecParseException(Exception):
    pass


class ChainSpec(ABC):
    @abstractmethod
    def instantiate(self, base: 'chain_options.ChainOptions') -> Iterable['chain_options.ChainOptions']:
        raise NotImplementedError

    @abstractmethod
    def iter(self, base: 'chain.Chain') -> Iterable['chain.Chain']:
        raise NotImplementedError

    def rebase(self, curr_base: 'chain_prototype.ChainPrototype', new_base: 'chain_prototype.ChainPrototype') -> 'ChainSpec':
        up_count = 0
        while curr_base != new_base:
            assert curr_base.parent is not None
            curr_base = curr_base.parent
            up_count += 1
        if isinstance(self, ChainSpecParent):
            self.up_count += up_count
            return self
        else:
            return ChainSpecParent(up_count, self)


class ChainSpecCurrent(ChainSpec):
    def instantiate(self, base: 'chain_options.ChainOptions') -> Iterable['chain_options.ChainOptions']:
        yield base

    def iter(self, base: 'chain.Chain') -> Iterable['chain.Chain']:
        yield base


class ChainSpecRoot(ChainSpec):
    rhs: ChainSpec

    def __init__(self, rhs: ChainSpec):
        self.rhs = rhs

    def instantiate(self, base: 'chain_options.ChainOptions') -> Iterable['chain_options.ChainOptions']:
        while base.parent is not None:
            base = base.parent
        yield base

    def iter(self, base: 'chain.Chain') -> Iterable['chain.Chain']:
        while base.parent is not None:
            base = base.parent
        yield base


class ChainSpecParent(ChainSpec):
    up_count: int
    rhs: 'ChainSpec'

    def __init__(self, up_count: int, rhs: 'ChainSpec'):
        super().__init__()
        self.up_count = up_count
        self.rhs = rhs

    def instantiate(self, base: 'chain_options.ChainOptions') -> Iterable['chain_options.ChainOptions']:
        for i in range(0, self.up_count):
            assert base.parent is not None
            base = base.parent
        yield from self.rhs.instantiate(base)

    def iter(self, base: 'chain.Chain') -> Iterable['chain.Chain']:
        for i in range(0, self.up_count):
            assert base.parent is not None
            base = base.parent
        yield from self.rhs.iter(base)


class ChainSpecSubrange(ChainSpec):
    subchain_range: 'range_spec.RangeSpec'
    rhs: ChainSpec

    def __init__(self, subchain_range: 'range_spec.RangeSpec', rhs: ChainSpec) -> None:
        super().__init__()
        self.subchain_range = subchain_range
        self.rhs = rhs

    def instantiate(self, base: 'chain_options.ChainOptions') -> Iterable['chain_options.ChainOptions']:
        explicit_max = self.subchain_range.explicit_max()
        if explicit_max > len(base.subchains):
            base.subchains.extend((chain_options.ChainOptions(parent=base) for _ in range(len(base.subchains), explicit_max)))
        for i in self.subchain_range.iter(len(base.subchains)):
            yield from self.rhs.instantiate(base.subchains[i])

    def iter(self, base: 'chain.Chain') -> Iterable['chain.Chain']:
        explicit_max = self.subchain_range.explicit_max()
        explicit_max = self.subchain_range.explicit_max()
        assert explicit_max <= len(base.subchains)
        for i in self.subchain_range.iter(len(base.subchains)):
            yield from self.rhs.iter(base.subchains[i])


def parse_chain_spec(cs: str, parent_cs: Optional[str] = None) -> ChainSpec:
    cs = cs.strip()
    first_slash = cs.rfind("/")

    if first_slash == 0:
        return ChainSpecRoot(parse_chain_spec(cs[1:], parent_cs))
    if first_slash != -1:
        rhs = parse_chain_spec(cs[first_slash+1:], parent_cs)
        cs = cs[:first_slash]
    else:
        rhs = ChainSpecCurrent()
    if cs == "":
        return rhs
    if cs.startswith("."):
        up_count = 0
        for i in range(1, len(cs)):
            if cs[i] != ".":
                raise ChainSpecParseException("unexpected character '{cs[i]}' in chain identifier {cs}")
        up_count = len(cs) - 1
        if up_count > 0:
            return ChainSpecParent(up_count, rhs)
    try:
        range = range_spec.parse_range_spec(cs, parent_cs)
    except range_spec.RangeSpecParseException as ex:
        raise ChainSpecParseException(*ex.args)
    return ChainSpecSubrange(range, rhs)