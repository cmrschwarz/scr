from abc import ABC, abstractmethod
from .definitions import (ScrSetupError, ScrMatchError, Verbosity)
from . import match_chain, scr, selenium_setup
from .document import Document
from .config_data_class import ConfigDataClass
from typing import Optional, Any, cast
import lxml.etree
import lxml.html
import re
from selenium.common.exceptions import WebDriverException as SeleniumWebDriverException
from selenium.common.exceptions import JavascriptException as SeleniumJavascriptException
from selenium.webdriver.remote.webdriver import WebDriver as SeleniumWebDriver
from urllib3.exceptions import MaxRetryError as SeleniumMaxRetryError
from .match_chain import MatchChain
import textwrap
import copy


class LocatorMatch:
    text: Optional[str]
    xml: Optional[lxml.html.HtmlElement]
    doc: Document
    match_args: dict[str, str]
    slots = tuple(__annotations__.keys())

    def set_regex_match(self, match: re.Match[str]) -> None:
        self.result = match.group(0)
        self.rmatch = self.result
        self.named_cgroups = {
            k: (v if v is not None else "")
            for (k, v) in match.groupdict().items()
        }
        self.unnamed_cgroups = [
            x if x is not None else "" for x in match.groups()
        ]

    def __init__(self, text: Optional[str] = None, xml: Optional[lxml.html.HtmlElement] = None):
        self.text = text
        self.xml = xml
        self.match_args = {}

    def __key__(self) -> tuple[Optional[str], Optional[lxml.html.HtmlElement], dict[str, str]]:
        return (self.text, self.xml, self.match_args)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, self.__class__) and self.__key__() == other.__key__()

    def __hash__(self) -> int:
        return hash(self.__key__())

    def unnamed_group_list_to_dict(self, name_prefix: str) -> dict[str, str]:
        if self.rmatch is None:
            return {}
        group_dict = {f"{name_prefix}0": self.rmatch}
        for i, g in enumerate(cast(list[str], self.unnamed_cgroups)):
            group_dict[f"{name_prefix}{i+1}"] = g
        return group_dict

    def copy(self) -> 'LocatorMatch':
        return copy.copy(self)


class MatchStep(ABC, ConfigDataClass):
    arg_val: str

    _config_slot_annotations_: dict[str, Any] = __annotations__

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

    def __init__(self, name: str, step_type_index: int, arg: str, arg_val: str) -> None:
        ConfigDataClass.__init__(self)
        self.name = name
        self.step_type_index = step_type_index
        self.try_set_config_option(["arg_val"], arg_val, arg)

    def apply_match_arg(self, lm: LocatorMatch, arg_name: str, arg_val: str) -> None:
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

    def needs_text(self) -> bool:
        return True

    def needs_xml(self) -> bool:
        return False

    def needs_xpath(self) -> bool:
        return False

    def is_order_dependent(self) -> bool:
        """ whether the step has observable behavior depending on the
        execution of earlier matches in the chain. examples of this include
        executing js or using the ci variable
        """
        return False


class RegexMatchStep(MatchStep):
    multimatch: bool = True
    multiline: bool = False
    case_insensitive: bool = False

    _config_slots_: list[str] = (
        MatchStep._annotations_as_config_slots(__annotations__, [])
    )
    step_type_index: int
    regex: re.Pattern[str]

    def __init__(self, name: str, step_type_index: int, arg: str, arg_val: str) -> None:
        super().__init__(name, step_type_index, arg, arg_val)

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


class JSMatchStep(MatchStep):
    multimatch: bool = False

    _config_slots_: list[str] = (
        MatchStep._annotations_as_config_slots(__annotations__, [])
    )
    loc: 'Locator'

    def __init__(self, name: str, step_type_index: int, arg: str, arg_val: str) -> None:
        super().__init__(name, step_type_index, arg, arg_val)

    def setup(self, loc: 'Locator', prev: Optional['MatchStep']) -> None:
        self.loc = loc
        args_dict: dict[str, Any] = {}
        dummy_doc = loc.mc.gen_dummy_document()
        scr.apply_general_format_args(dummy_doc, loc.mc, args_dict, ci=None)
        dummy_loc_match = LocatorMatch()
        if prev is not None:
            prev.apply_partial_chain_to_dummy_locator_match(loc, dummy_loc_match)
        args_dict.update(dummy_loc_match.match_args)
        js_prelude = ""
        for i, k in enumerate(args_dict.keys()):
            js_prelude += f"const {k} = arguments[{i}];\n"
        self.js_script = js_prelude + self.arg_val

    def apply(self, lms: list[LocatorMatch]) -> list[LocatorMatch]:
        lms_new: list[LocatorMatch] = []
        for lm in lms:
            args_dict: dict[str, Any] = lm.named_cgroups
            try:
                drv = cast(SeleniumWebDriver, self.loc.mc.ctx.selenium_driver)
                results = drv.execute_script(self.js_script, *args_dict.values())  # type: ignore

            except SeleniumJavascriptException as ex:
                arg = cast(str, self.get_configuring_argument(['js_script']))
                name = arg[0: arg.find("=")]
                if self.loc.mc.ctx.last_doc_path:
                    on = f" on {self.loc.mc.ctx.last_doc_path}"
                else:
                    on = ""
                scr.log(
                    self.loc.mc.ctx, Verbosity.WARN,
                    f"{name}: js exception{on}:\n{textwrap.indent(str(ex), '    ')}"
                )
                continue
            except (SeleniumWebDriverException, SeleniumMaxRetryError):
                if selenium_setup.selenium_has_died(self.loc.mc.ctx):
                    raise ScrMatchError(
                        "the selenium instance was closed unexpectedly")
                continue
            if results is None:
                continue
            if type(results) is not list:
                results = [str(results)]
            res: Optional[LocatorMatch] = lm
            for r in results:
                if res is None:
                    res = lm.copy()
                self.apply_match_arg(res, "", r)
                res.result = r
                lms_new.append(res)
                if not self.multimatch:
                    break
                res = None
        return lms_new

    def needs_xpath(self) -> bool:
        return True

    def is_order_dependent(self) -> bool:
        return True


class PythonFormatStringMatchStep(MatchStep):
    _config_slots_: list[str] = (
        MatchStep._annotations_as_config_slots(__annotations__, [])
    )
    loc: 'Locator'

    def __init__(self, name: str, step_type_index: int, arg: str, arg_val: str) -> None:
        super().__init__(name, step_type_index, arg, arg_val)

    def setup(self, loc: 'Locator', prev: Optional['MatchStep']) -> None:
        self.loc = loc
        scr.validate_format(
            self, ["format"], loc.mc.gen_dummy_content_match(not loc.mc.content_raw), True, False
        )

    def apply(self, lms: list[LocatorMatch]) -> list[LocatorMatch]:
        for i, lm in enumerate(lms):
            args_dict: dict[str, str] = {}
            scr.apply_general_format_args(lm.doc, self.loc.mc, args_dict, self.loc.mc.ci + i)
            args_dict.update(lm.match_args)
            lm.text = self.arg_val.format(**args_dict)
        return lms

    def is_order_dependent(self) -> bool:
        return scr.format_string_arg_occurence(self.arg_val, "ci") != 0


class Locator(ConfigDataClass):
    name: str
    xpath_sibling_match_depth: int = 0

    __annotations__: dict[str, type]

    _config_slots_: list[str] = (
        ConfigDataClass._annotations_as_config_slots(
            __annotations__, []
        )
    )
    mc: MatchChain  # initialized on setup
    match_steps: list[MatchStep]
    first_order_dependant_step: int
    last_xpath_needing_step: int
    # steps that can be executed before interactive selenium deduplication

    def __init__(self, name: str, blank: bool = False) -> None:
        super().__init__(blank)
        self.name = name
        self.match_steps = []
        self.first_order_dependant_step = 0

    def is_active(self) -> bool:
        return len(self.match_steps) != 0

    def needs_document_content(self) -> bool:
        return any(ms.needs_text() for ms in self.match_steps)

    def is_order_dependant(self) -> bool:
        return self.first_order_dependant_step == len(self.match_steps)

    def gen_dummy_locator_match(self) -> LocatorMatch:
        lm = LocatorMatch()
        for ms in self.match_steps:
            ms.apply_to_dummy_locator_match(lm)
        return lm

    def setup(self, mc: 'match_chain.MatchChain') -> None:
        self.mc = mc
        for i in range(len(self.match_steps)):
            self.match_steps[i].setup(self, self.match_steps[i - 1] if i > 0 else None)
