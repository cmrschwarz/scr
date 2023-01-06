from scr.transforms import transform
from scr.match import MatchConcrete, MatchEager
from typing import Optional
import time
import math


class Sleep(transform.TransformLazy):
    sleep_time_seconds: float

    @staticmethod
    def name_matches(name: str) -> bool:
        return "sleep".startswith(name)

    @staticmethod
    def create(label: str, value: Optional[str], chainspec: 'chain_spec.ChainSpec') -> 'transform.Transform':
        if value is None:
            raise transform.TransformValueError("missing sleep time argument")
        try:
            sts = float(value)
            if math.isnan(sts) or math.isinf(sts) or sts < 0:
                raise transform.TransformValueError("invalid sleep time {arg}")
            return Sleep(label, sts)
        except (FloatingPointError, transform.TransformValueError, TypeError, OverflowError):
            raise transform.TransformValueError("invalid sleep time {arg}")

    def __init__(self, label: str, sleep_time_seconds: float) -> None:
        super().__init__(label)

    def apply_concrete(self, m: MatchConcrete) -> MatchEager:
        time.sleep(self.sleep_time_seconds)
        return m
