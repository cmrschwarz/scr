from .match_step import MatchStep
from ..locator import Locator, LocatorMatch
from .. import scr
from ..definitions import FILENAME_REQUIRING_FORMAT_SPECIFIERS
from typing import Optional


class PythonFormatStringMatchStep(MatchStep):
    _config_slots_: list[str] = (
        MatchStep._annotations_as_config_slots(__annotations__, [])
    )
    loc: 'Locator'

    def __init__(self, index: int, name: str, step_type_occurence_count: int, arg: str, arg_val: str) -> None:
        super().__init__(index, name, step_type_occurence_count, arg, arg_val)

    def setup(self, loc: 'Locator', prev: Optional['MatchStep']) -> None:
        self.loc = loc
        scr.validate_format(
            self, ["format"], loc.mc.gen_dummy_content_match(not loc.mc.content_raw), True, False
        )

    def apply(self, lms: list[LocatorMatch]) -> list[LocatorMatch]:
        for i, lm in enumerate(lms):
            args_dict: dict[str, str] = {}
            assert lm.doc is not None
            scr.apply_general_format_args(lm.doc, self.loc.mc, args_dict, self.loc.mc.ci + i)
            args_dict.update(lm.match_args)
            lm.text = self.arg_val.format(**args_dict)
        return lms

    def is_order_dependent(self) -> bool:
        return scr.format_string_arg_occurence(self.arg_val, "ci") != 0

    def needs_filename(self) -> bool:
        return any(scr.format_string_arg_occurence(self.arg_val, arg) != 0 for arg in FILENAME_REQUIRING_FORMAT_SPECIFIERS)
