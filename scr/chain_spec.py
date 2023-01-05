
from typing import Iterable, Optional
from abc import ABC, abstractmethod
from scr import chain, range_spec, chain_options


class ChainSpecParseException(Exception):
    pass


class ChainSpec(ABC):
    @abstractmethod
    def instantiate(self, base: 'chain_options.ChainOptions') -> Iterable['chain_options.ChainOptions']:
        raise NotImplementedError

    @abstractmethod
    def iter(self, base: 'chain.Chain') -> Iterable['chain.Chain']:
        raise NotImplementedError


class ChainSpecParent(ChainSpec):
    up_count: int

    def __init__(self, up_count: int):
        super().__init__()
        self.up_count = up_count

    def instantiate(self, base: 'chain_options.ChainOptions') -> Iterable['chain_options.ChainOptions']:
        curr = base
        for i in range(0, self.up_count):
            if curr.parent is None:
                break
            curr = curr.parent
        yield curr

    def iter(self, base: 'chain.Chain') -> Iterable['chain.Chain']:
        curr = base
        for i in range(0, self.up_count):
            if curr.parent is None:
                break
            curr = curr.parent
        yield curr


class ChainSpecSubrange(ChainSpec):
    base: ChainSpec
    subchain_range: 'range_spec.RangeSpec'

    def __init__(self, base: ChainSpec, subchain_range: 'range_spec.RangeSpec') -> None:
        super().__init__()
        self.base = base
        self.subchain_range = subchain_range

    def instantiate(self, base: 'chain_options.ChainOptions') -> Iterable['chain_options.ChainOptions']:
        explicit_max = self.subchain_range.explicit_max()
        for cs in self.base.instantiate(base):
            if explicit_max > len(cs.subchains):
                cs.subchains.extend((chain_options.ChainOptions(parent=cs) for _ in range(len(cs.subchains), explicit_max)))
            for sc in self.subchain_range.iter(len(cs.subchains)):
                yield cs.subchains[sc]

    def iter(self, base: 'chain.Chain') -> Iterable['chain.Chain']:
        explicit_max = self.subchain_range.explicit_max()
        for cs in self.base.iter(base):
            assert explicit_max <= len(cs.subchains)
            for sc in self.subchain_range.iter(len(cs.subchains)):
                yield cs.subchains[sc]


def parse_chain_spec(cs: str, parent_cs: Optional[str] = None) -> ChainSpec:
    cs = cs.strip()
    last_slash = cs.rfind("/")
    try:
        if last_slash != -1:
            return ChainSpecSubrange(
                parse_chain_spec(cs[0:last_slash], parent_cs),
                range_spec.parse_range_spec(cs[last_slash+1:], parent_cs)
            )
        if cs.startswith("."):
            up_count = 0
            for i in range(1, len(cs)):
                if cs[i] != ".":
                    raise ChainSpecParseException("unexpected character '{cs[i]}' in chain identifier {cs}")
            up_count = len(cs) - 1
            return ChainSpecParent(up_count)

        return ChainSpecSubrange(ChainSpecParent(0), range_spec.parse_range_spec(cs, parent_cs))

    except range_spec.RangeSpecParseException as ex:
        raise ChainSpecParseException(*ex.args)
