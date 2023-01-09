from scr.transforms import transform
from scr import chain_spec, match, chain_prototype
from typing import Optional, Type
import time
import math


class Sleep(transform.TransformLazy):
    sleep_time_seconds: float

    @staticmethod
    def name_matches(name: str) -> bool:
        return "sleep".startswith(name)

    def input_match_types(self) -> Optional[set[Type[match.MatchConcrete]]]:
        return None

    def output_match_types(self) -> Optional[set[Type[match.MatchConcrete]]]:
        return None

    @staticmethod
    def create(label: str, value: Optional[str], current: 'chain_prototype.ChainPrototype', chainspec: 'chain_spec.ChainSpec') -> 'transform.Transform':
        if value is None:
            raise transform.TransformCreationError("missing sleep time argument")
        try:
            sts = float(value)
            if math.isnan(sts) or math.isinf(sts) or sts < 0:
                raise transform.TransformCreationError("invalid sleep time {arg}")
            return Sleep(label, sts)
        except (FloatingPointError, TypeError, OverflowError):
            raise transform.TransformCreationError("invalid sleep time {arg}")

    def __init__(self, label: str, sleep_time_seconds: float) -> None:
        super().__init__(label)
        self.sleep_time_seconds = sleep_time_seconds

    def apply_concrete(self, m: match.MatchConcrete) -> match.MatchEager:
        time.sleep(self.sleep_time_seconds)
        return m
