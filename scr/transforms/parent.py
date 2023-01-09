from scr.transforms import transform
from scr import chain_spec, match, chain, chain_prototype
from typing import Optional, Type


class Parent(transform.Transform):
    skip_num: int

    @staticmethod
    def name_matches(name: str) -> bool:
        return "parent".startswith(name) and len(name) > 1

    def input_match_types(self) -> Optional[set[Type[match.MatchConcrete]]]:
        return None

    def output_match_types(self) -> Optional[set[Type[match.MatchConcrete]]]:
        return None

    @staticmethod
    def create(label: str, value: Optional[str], current: 'chain_prototype.ChainPrototype', chainspec: 'chain_spec.ChainSpec') -> 'transform.Transform':
        if value is not None:
            try:
                skip_num = int(value)
            except (ValueError, TypeError, OverflowError):
                raise transform.TransformCreationError("invalid skip number for 'parent'")
            if skip_num <= 0:
                raise transform.TransformCreationError("skip number for 'parent' must be greater than 0")
        else:
            skip_num = 1
        return Parent(label, skip_num)

    def __init__(self, label: str, skip_num: int = 1) -> None:
        super().__init__(label)
        self.skip_num = skip_num

    def apply_now(self, cn: 'chain.Chain', m: 'match.Match') -> 'match.Match':
        p = m
        for i in range(0, self.skip_num):
            if p.parent is None:
                raise transform.TransformApplicationError(cn, self, "'parent' failed: match has no parent")
            p = p.parent
        return p

    def apply(self, cn: 'chain.Chain', m: 'match.Match') -> 'match.Match':
        return m.apply_now(lambda m: self.apply_now(cn, m))
