
from abc import ABC, abstractmethod
from .range_spec import parse_range_spec, RangeSpecParseException

class ChainSpecParseException(Exception):
    pass

class ChainSpec(ABC):
    @abstractmethod
    def instantiate(self) -> Iterable['Chain']:
        raise NotImplementedError

class ChainSpecSingle(ChainSpec):
    parent_ref: int

    def __init__(self, parent_ref: int):
        super().__init__()
        self.parent_ref = parent_ref

    def instantiate(self, root) -> Iterable['Chain']:
        chain = root
        for i in range(0, self.parent_ref):
            if chain.parent is None:
                break
            chain = chain.parent
        yield chain


class ChainSpecSubrange(ChainSpec):
    parent: Option[ChainSpec]
    subchains: RangeSpec

    def __init__(self, parent, subchains):
        super().__init__()
        self.parent = parent
        self.subchains = subchains

    def instantiate(self, root: Chain) -> Iterable['Chain']:
        explicit_max = self.subchains.explicit_max()
        for cs in self.parent.iter():
            if explicit_max > len(cs.subchains):
                cs.subchains.extend((cs.subchain_template.clone(i) for i in range(len(cs.subchains), explicit_max)))
            for sc in subchains.iter(len(cs.subchains)):
                yield cs.subchains[sc]


def parse_chain_spec(cs: str, parent_cs: Option[str] = None) -> ChainSpec:
    cs = cs.strip()
    last_colon = cs.rfind(":")
    try:
        if last_colon != -1:
            return ChainSpecSubrange(
                parse_chain_spec(root, cs[0:last_colon], parent_cs),
                parse_range_spec(cs[last_colon+1:], parent_cs)
            )
        if cs.startswith("."):
            parent_ref = 0
            for i in range(1, len(cs)):
                if cs[i] != ".":
                    raise ChainSpecParseException("unexpected character '{cs[i]}' in chain identifier {cs}")
            parent_ref = len(cs) - 1
            return ChainSpecSingle(parent_ref)

        return ChainSpecSubrange(ChainSpecSingle(), parse_range_spec_int(cs, parent_cs))

    except RangeSpecParseException as ex:
        raise ChainSpecParseException(ex.message)
