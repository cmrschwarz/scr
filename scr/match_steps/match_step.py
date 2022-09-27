from ..config_data_class import ConfigDataClass
from ..locator import LocatorMatch, Locator

from abc import ABC, abstractmethod
from typing import Optional,  Any


class MatchStep(ABC, ConfigDataClass):
    arg_val: str

    _config_slot_annotations_: dict[str, Any] = __annotations__

    step_index: int
    name: str
    name_short: str

    @staticmethod
    def _annotations_as_config_slots(
        annotations: dict[str, Any],
        subconfig_slots: list[str]
    ) -> list[str]:
        annots = MatchStep._config_slot_annotations_.copy()
        annots.update(annotations)
        return ConfigDataClass._annotations_as_config_slots(annots, subconfig_slots)

    def __init__(self, index: int, name: str, step_type_occurence_count: int, arg: str, arg_val: str) -> None:
        ConfigDataClass.__init__(self)
        self.name = name
        self.step_type_occurence_count = step_type_occurence_count
        self.try_set_config_option(["arg_val"], arg_val, arg)

    def apply_match_arg(self, lm: 'LocatorMatch', arg_name: str, arg_val: str) -> None:
        lm.match_args[self.name + arg_name] = arg_val
        lm.match_args[self.name_short + arg_name] = arg_val

    def apply_partial_chain_to_dummy_locator_match(self, loc: 'Locator', dlm: 'LocatorMatch') -> None:
        for ms in loc.match_steps:
            ms.apply_to_dummy_locator_match(dlm)
            if ms is self:
                break

    @abstractmethod
    def setup(self, loc: 'Locator', prev: Optional['MatchStep']) -> None:
        pass

    @abstractmethod
    def apply(self, lms: list[LocatorMatch]) -> list[LocatorMatch]:
        pass

    def apply_to_dummy_locator_match(self, lm: LocatorMatch) -> None:
        self.apply_match_arg(lm, "", "")

    def has_multimatch(self) -> bool:
        return False

    def needs_xml(self) -> bool:
        return False

    def needs_filename(self) -> bool:
        return False

    def needs_xpath(self) -> bool:
        return False

    def is_order_dependent(self) -> bool:
        """ whether the step has observable behavior depending on the
        execution of earlier matches in the chain. examples of this include
        executing js or using the {ci} variable
        """
        return False
