from scr.transforms import transform
from scr import chain_spec, chain, chain_options, match, chain_prototype
from typing import Optional, Type


class Up(transform.Transform):
    up_count: int

    @staticmethod
    def name_matches(name: str) -> bool:
        return "up".startswith(name)

    def input_match_types(self) -> Optional[set[Type[match.MatchConcrete]]]:
        return None

    def output_match_types(self) -> Optional[set[Type[match.MatchConcrete]]]:
        return None

    @staticmethod
    def create(label: str, value: Optional[str], current: 'chain_prototype.ChainPrototype', chainspec: 'chain_spec.ChainSpec') -> 'transform.Transform':
        if value is not None:
            try:
                up_count = int(value)
            except (ValueError, TypeError, OverflowError):
                raise transform.TransformCreationError("invalid up count for 'up'")
            if up_count <= 0:
                raise transform.TransformCreationError("up count for 'up' must be greater than 0")
        else:
            up_count = 1
        return Up(label, up_count)

    def __init__(self, label: str, up_count: int) -> None:
        super().__init__(label)
        self.up_count = up_count

    def apply(self, cn: 'chain.Chain', m: 'match.Match') -> 'match.Match':
        return m

    def get_next_chain_context(self, current: 'chain_options.ChainOptions') -> 'chain_options.ChainOptions':
        p = current
        for _ in range(0, self.up_count):
            if p.parent is None:
                if current.parent is None:
                    raise transform.TransformCreationError("cannot go up from root chain")
                raise transform.TransformCreationError(f"cannot go up {self.up_count} times from chain {current}")
            p = p.parent
        return p
