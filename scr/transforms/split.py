from scr.transforms import transform, transform_ref
from scr import chain_spec, chain, chain_options, match, range_spec
from typing import Optional


class Split(transform.Transform):
    min: int
    max: Optional[int]

    @staticmethod
    def name_matches(name: str) -> bool:
        return "split".startswith(name)

    @staticmethod
    def create(label: str, value: Optional[str], chainspec: 'chain_spec.ChainSpec') -> 'transform.Transform':
        if value is None:
            return Split(label)
        try:
            rs = range_spec.parse_range_spec(value)
            if isinstance(rs, range_spec.RangeSpecValue):
                return Split(label, rs.value)
            elif isinstance(rs, range_spec.RangeSpecBounds) and rs.min is not None:
                return Split(label, rs.min, rs.max)
            raise transform.TransformValueError("invalid range for 'split': must be either index or simple range")
        except range_spec.RangeSpecParseException as ex:
            raise transform.TransformValueError(f"invalid range for 'split': {ex}")

    def __init__(self, label: str, min: int = 0, max: Optional[int] = None) -> None:
        super().__init__(label)
        self.min = min
        self.max = max

    def apply(self, c: 'chain.Chain', m: 'match.Match') -> 'match.Match':
        cfr = match.MatchControlFlowRedirect(m)
        for i in range(self.min, self.max if self.max is not None else len(c.subchains)):
            cfr.matches.append((transform_ref.TransformRef(c.subchains[i], 0), m))
        return cfr

    def get_next_chain_context(self, current: 'chain_options.ChainOptions') -> 'chain_options.ChainOptions':
        while len(current.subchains) <= self.min:
            current.subchains.append(chain_options.ChainOptions(parent=current))
        return current.subchains[self.min]
