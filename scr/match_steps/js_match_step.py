from .match_step import MatchStep
from ..locator import Locator, LocatorMatch
from .. import scr, selenium_setup
from ..definitions import (ScrMatchError, Verbosity)


from typing import Optional, cast, Any
from selenium.common.exceptions import WebDriverException as SeleniumWebDriverException
from selenium.common.exceptions import JavascriptException as SeleniumJavascriptException
from selenium.webdriver.remote.webdriver import WebDriver as SeleniumWebDriver
from urllib3.exceptions import MaxRetryError as SeleniumMaxRetryError
import textwrap


class JSMatchStep(MatchStep):
    multimatch: bool = False

    _config_slots_: list[str] = (
        MatchStep._annotations_as_config_slots(__annotations__, [])
    )
    loc: 'Locator'

    def __init__(self, index: int, name: str, step_type_occurence_count: int, arg: str, arg_val: str) -> None:
        super().__init__(index, name, step_type_occurence_count, arg, arg_val)

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

    def has_multimatch(self) -> bool:
        return self.multimatch
