from .match_step import MatchStep
from ..locator import Locator, LocatorMatch
from ..definitions import ScrSetupError

from typing import Optional, cast, Any
import re


class RegexMatchStep(MatchStep):
    multimatch: bool = True
    multiline: bool = False
    case_insensitive: bool = False

    _config_slots_: list[str] = (
        MatchStep._annotations_as_config_slots(__annotations__, [])
    )
    step_type_occurence_count: int
    regex: re.Pattern[str]

    def __init__(self, index: int, name: str, step_type_occurence_count: int, arg: str, arg_val: str) -> None:
        super().__init__(index, name, step_type_occurence_count, arg, arg_val)

    def setup(self, loc: 'Locator', prev: Optional['MatchStep']) -> None:
        try:
            self.regex = re.compile(self.arg_val, re.DOTALL | re.MULTILINE)
        except re.error as err:
            raise ScrSetupError(
                f"invalid regex ({err.msg}) in {self.get_configuring_argument(['regex'])}"
            )

    def apply_regex_match_args(self, lm: 'LocatorMatch', named_cgroups: dict[str, Any], unnamed_cgroups: list[Any]) -> None:
        for k, v in named_cgroups.items():
            val = str(v) if v is not None else ""
            self.apply_match_arg(lm, k, val)
            lm.match_args[k] = val

        for i, g in enumerate(unnamed_cgroups):
            val = str(g) if g is not None else ""
            self.apply_match_arg(lm, str(i), val)

    def apply_regex_match_match_args(self, lm: 'LocatorMatch', match: re.Match[str]) -> None:
        self.apply_regex_match_args(lm, match.groupdict(), cast(list[Any], match.groups()))

    def apply_to_dummy_locator_match(self, lm: LocatorMatch) -> None:
        lm.rmatch = ""
        capture_group_keys = list(self.regex.groupindex.keys())
        unnamed_regex_group_count = (
            self.regex.groups - len(capture_group_keys)
        )
        self.apply_regex_match_args(
            lm,
            {k: "" for k in capture_group_keys},
            [""] * unnamed_regex_group_count
        )
        self.apply_match_arg(lm, "", "")

    def apply(self, lms: list[LocatorMatch]) -> list[LocatorMatch]:
        if self.regex is None:
            return lms
        lms_new = []
        for lm in lms:
            if not self.multimatch:
                match = self.regex.match(lm.result)
                if match:
                    self.apply_regex_match_match_args(lm, match)
                    lms_new.append(lm)
                continue
            res: Optional[LocatorMatch] = lm
            for match in self.regex.finditer(lm.result):
                if res is None:
                    res = lm.copy()
                self.apply_regex_match_match_args(lm, match)
                lms_new.append(res)
                if not self.multimatch:
                    break
                res = None
        return lms_new

    def has_multimatch(self) -> bool:
        return self.multimatch
