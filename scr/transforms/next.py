from scr.transforms import transform
from scr.match import MatchConcrete, MatchEager
from scr import chain_prototype, chain_spec, chain, chain_options
from typing import Iterable, Optional
import time
import math


class Next(transform.TransformEager):
    target: 'chain_spec.ChainSpec'

    @staticmethod
    def name_matches(name: str) -> bool:
        return "next".startswith(name)

    @staticmethod
    def create(label: str, value: Optional[str]) -> 'transform.Transform':
        if value is None:
            return Next(label, chain_spec.ChainSpecSibling(1))
        try:
            sts = float(value)
            if math.isnan(sts) or math.isinf(sts) or sts < 0:
                raise transform.TransformValueError("invalid sleep time {arg}")
            return Next(label, chain_spec.parse_chain_spec(value))
        except (FloatingPointError, transform.TransformValueError, TypeError, OverflowError):
            raise transform.TransformValueError("invalid sleep time {arg}")

    def __init__(self, label: str, target: 'chain_spec.ChainSpec') -> None:
        super().__init__(label)

    def apply_concrete(self, m: MatchConcrete) -> MatchEager:
        return m

    def get_next_chain_context(self, current: 'chain_options.ChainOptions') -> 'chain_options.ChainOptions':
        res = None
        for tc in self.target.instantiate(current):
            assert res is None
            res = tc
        assert res is not None
        return res
