from typing import Any, NoReturn, Generator
import pytest
from .. import utils
import sys
import platform
import datetime


@pytest.fixture()
def pretend_windows() -> Generator[bool, None, None]:
    system_func = platform.system
    sys_platform_value = sys.platform

    def plattform_dummy_fn(*args: Any, **kwargs: Any) -> str:
        return "Windows"
    platform.system = plattform_dummy_fn
    sys.platform = "win32"
    yield True
    platform.system = system_func
    sys.platform = sys_platform_value


FAKE_TIME_ORIGIN = datetime.datetime.min
FAKE_TIME_NOW = (datetime.datetime.min + datetime.timedelta(seconds=60))


@pytest.fixture()
def _fake_time(monkeypatch: pytest.MonkeyPatch) -> None:
    class mydatetime(datetime.datetime):
        @classmethod
        def now(cls: Any, tz: Any = None) -> Any:
            return FAKE_TIME_NOW
    monkeypatch.setattr(datetime, 'datetime', mydatetime)


# this makes sure that exceptions in tests are raise properly
# see https://stackoverflow.com/questions/62419998/how-can-i-get-pytest-to-not-catch-exceptions
if utils.is_debugger_attached():
    @pytest.hookimpl(tryfirst=True)  # type: ignore
    def pytest_exception_interact(call: Any) -> NoReturn:
        raise call.excinfo.value

    @pytest.hookimpl(tryfirst=True)  # type: ignore
    def pytest_internalerror(excinfo: Any) -> NoReturn:
        raise excinfo.value
