from typing import Any, NoReturn
import pytest
from .. import utils

# this makes sure that exceptions in tests are raise properly
# see https://stackoverflow.com/questions/62419998/how-can-i-get-pytest-to-not-catch-exceptions
if utils.is_debugger_attached():
    @pytest.hookimpl(tryfirst=True)  # type: ignore
    def pytest_exception_interact(call: Any) -> NoReturn:
        raise call.excinfo.value

    @pytest.hookimpl(tryfirst=True)  # type: ignore
    def pytest_internalerror(excinfo: Any) -> NoReturn:
        raise excinfo.value
