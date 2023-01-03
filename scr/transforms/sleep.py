from scr.transforms import transform
from scr.match import MatchConcrete, MatchEager
import time
import math


class Sleep(transform.TransformLazy):
    sleep_time_seconds: float

    @staticmethod
    def name_matches(name: str) -> bool:
        return "sleep".startswith(name)

    def __init__(self, label: str, arg: str) -> None:
        super().__init__(label)
        try:
            sts = float(arg)
            if math.isnan(sts) or math.isinf(sts) or sts < 0:
                raise ValueError("invalid sleep time {arg}")
            self.sleep_time_seconds = sts
        except (FloatingPointError, ValueError, TypeError, OverflowError):
            raise ValueError("invalid sleep time {arg}")

    def apply_concrete(self, m: MatchConcrete) -> MatchEager:
        time.sleep(self.sleep_time_seconds)
        return m
