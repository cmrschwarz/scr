from selenium.webdriver.firefox.service import Service as SeleniumFirefoxService
from selenium.webdriver.chrome.service import Service as SeleniumChromeService
from selenium.common.exceptions import WebDriverException as SeleniumWebDriverException
from selenium.common.exceptions import TimeoutException as SeleniumTimeoutException
from tbselenium.tbdriver import TorBrowserDriver
import selenium.webdriver
import mimetypes
import functools
import subprocess
import os
import sys
from typing import Any, Optional, cast
from . import (scr_context, selenium_driver_download, utils, scr)
from .definitions import (SeleniumVariant, ScrSetupError, verbosities_display_dict, Verbosity, SCRIPT_NAME)

# this is of course not really a selenium exception,
# but selenium throws it arbitrarily, just like SeleniumWebDriverException,
# and that is the only way in which we use it
from urllib3.exceptions import MaxRetryError as SeleniumMaxRetryError


def load_selenium_cookies(ctx: 'scr_context.ScrContext') -> dict[str, dict[str, dict[str, Any]]]:
    assert ctx.selenium_driver is not None
    # the selenium function isn't type annotated properly
    cookies: list[dict[str, Any]
                  ] = ctx.selenium_driver.get_cookies()  # type: ignore
    cookie_dict: dict[str, dict[str, dict[str, Any]]] = {}
    for ck in cookies:
        if cast(str, ck["domain"]) not in cookie_dict:
            cookie_dict[ck["domain"]] = {}
        cookie_dict[ck["domain"]][ck["name"]] = ck
    return cookie_dict


def selenium_build_firefox_options(
    ctx: 'scr_context.ScrContext'
) -> selenium.webdriver.FirefoxOptions:
    ff_options = selenium.webdriver.FirefoxOptions()
    if ctx.selenium_headless:
        ff_options.headless = True
    if ctx.user_agent is not None:
        ff_options.set_preference("general.useragent.override", ctx.user_agent)
        if ctx.selenium_variant == SeleniumVariant.TORBROWSER:
            # otherwise the user agent is not applied
            ff_options.set_preference("privacy.resistFingerprinting", False)

    prefs = {}
    # setup download dir and disable save path popup
    if ctx.downloads_temp_dir is not None:
        mimetypes.init()
        save_mimetypes = ";".join(set(mimetypes.types_map.values()))
        prefs.update({
            "browser.download.dir": ctx.downloads_temp_dir,
            "browser.download.useDownloadDir": True,
            "browser.download.folderList": 2,
            "browser.download.manager.showWhenStarting": False,
            "browser.helperApps.neverAsk.saveToDisk": save_mimetypes,
            "browser.helperApps.showOpenOptionForViewableInternally": False,
            "pdfjs.disabled": True,
        })
    # make sure new tabs don't open new windows
    prefs.update({
        "browser.link.open_newwindow": 3,
        "browser.link.open_newwindow.restriction": 0,
        "browser.link.open_newwindow.override.external": -1,
    })

    # apply prefs
    for pk, pv in prefs.items():
        ff_options.set_preference(pk, pv)
    return ff_options


def setup_selenium_tor(ctx: 'scr_context.ScrContext') -> None:
    cwd = os.getcwd()
    selenium_driver_download.put_local_selenium_driver_in_path(
        ctx, SeleniumVariant.TORBROWSER
    )
    if ctx.tor_browser_dir is None:
        tb_env_var = "TOR_BROWSER_DIR"
        if tb_env_var in os.environ:
            ctx.tor_browser_dir = os.environ[tb_env_var]
        else:
            raise ScrSetupError("no tbdir specified, check --help")
    try:
        ctx.selenium_driver = TorBrowserDriver(
            ctx.tor_browser_dir, tbb_logfile_path=ctx.selenium_log_path,
            options=selenium_build_firefox_options(ctx)
        )

    except SeleniumWebDriverException as ex:
        err_msg = f"failed to start tor browser: {str(ex)}"
        if selenium_driver_download.try_get_local_selenium_driver_path(SeleniumVariant.TORBROWSER) is None:
            # same hack as for firefox
            err_msg += f"\n{verbosities_display_dict[Verbosity.INFO]}consider running '{SCRIPT_NAME} selinstall=torbrowser'"
        raise ScrSetupError(err_msg)
    os.chdir(cwd)  # restore cwd that is changed by tor for some reason


def setup_selenium_firefox(ctx: 'scr_context.ScrContext') -> None:
    selenium_driver_download.put_local_selenium_driver_in_path(
        ctx, SeleniumVariant.FIREFOX
    )
    try:
        ctx.selenium_driver = selenium.webdriver.Firefox(
            options=selenium_build_firefox_options(ctx),
            service=SeleniumFirefoxService(  # type: ignore
                log_path=ctx.selenium_log_path
            )
        )
    except (SeleniumWebDriverException, OSError) as ex:
        err_msg = f"failed to start geckodriver: {utils.truncate(str(ex))}"

        if selenium_driver_download.try_get_local_selenium_driver_path(SeleniumVariant.FIREFOX) is None:
            # this is slightly hacky, but i like the way it looks
            err_msg += f"\n{verbosities_display_dict[Verbosity.INFO]}consider running '{SCRIPT_NAME} selinstall=firefox'"
        raise ScrSetupError(err_msg)


def setup_selenium_chrome(ctx: 'scr_context.ScrContext') -> None:
    selenium_driver_download.put_local_selenium_driver_in_path(
        ctx, SeleniumVariant.CHROME
    )

    options = selenium.webdriver.ChromeOptions()
    options.binary_location = ""
    browser_path = selenium_driver_download.find_chrome_binary()
    if ctx.selenium_headless:
        options.headless = True
    options.add_argument("--incognito")
    if browser_path is not None:
        options.binary_location = browser_path
    if ctx.user_agent is not None:
        options.add_argument(f"user-agent={ctx.user_agent}")
    if ctx.downloads_temp_dir is not None:
        prefs = {
            "download.default_directory": ctx.downloads_temp_dir,
            "download.prompt_for_download": False,
            "profile.default_content_setting_values.automatic_downloads": 1,
        }
        options.add_experimental_option("prefs", prefs)
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    try:
        ctx.selenium_driver = selenium.webdriver.Chrome(
            options=options,
            service=SeleniumChromeService(  # type: ignore
                log_path=ctx.selenium_log_path
            )
        )
    except (SeleniumWebDriverException, OSError) as ex:
        err_msg = f"failed to start chromedriver: {utils.truncate(str(ex))}"

        if selenium_driver_download.try_get_local_selenium_driver_path(SeleniumVariant.CHROME) is None:
            # same hack as for firefox
            err_msg += f"\n{verbosities_display_dict[Verbosity.INFO]}consider running '{SCRIPT_NAME} selinstall=chrome'"
        raise ScrSetupError(err_msg)


def selenium_add_cookies_through_get(ctx: 'scr_context.ScrContext') -> None:
    # ctx.selenium_driver.set_page_load_timeout(0.01)
    assert ctx.selenium_driver is not None
    for domain, cookies in ctx.cookie_dict.items():
        try:
            ctx.selenium_driver.get(f"https://{domain}")
        except SeleniumTimeoutException:
            scr.log(
                ctx, Verbosity.WARN,
                "Failed to apply cookies for https://{domain}: page failed to load"
            )
        for c in cookies.values():
            ctx.selenium_driver.add_cookie(c)


def selenium_start_wrapper(*args: Any, **kwargs: Any) -> None:
    assert sys.platform != "win32"

    def preexec_function() -> None:
        # this makes sure that the selenium instance does not die on SIGINT
        os.setpgrp()
    original_p_open = subprocess.Popen
    subprocess.Popen = functools.partial(  # type: ignore
        subprocess.Popen, preexec_fn=preexec_function
    )
    try:
        selenium_start_wrapper.original_start(*args, **kwargs)  # type: ignore
    finally:
        subprocess.Popen = original_p_open  # type: ignore


def prevent_selenium_sigint() -> None:
    if utils.is_windows():
        # TODO
        return
    if selenium.webdriver.common.service.Service.start is selenium_start_wrapper:
        return
    selenium_start_wrapper.original_start = selenium.webdriver.common.service.Service.start  # type: ignore
    selenium.webdriver.common.service.Service.start = selenium_start_wrapper  # type: ignore


def selenium_exec_script(ctx: 'scr_context.ScrContext', script: str, *args: Any) -> Any:
    assert ctx.selenium_driver is not None
    # execute_script is not annotated -> we have to eat the type error
    return ctx.selenium_driver.execute_script(script, *args)  # type: ignore


def selenium_get_url(ctx: 'scr_context.ScrContext') -> Optional[str]:
    assert ctx.selenium_driver is not None
    try:
        return cast(str, ctx.selenium_driver.current_url)
    except (SeleniumWebDriverException, SeleniumMaxRetryError):
        report_selenium_died(ctx)
        return None


def selenium_has_died(ctx: 'scr_context.ScrContext') -> bool:
    assert ctx.selenium_driver is not None
    try:
        # throws an exception if the session died
        return not len(ctx.selenium_driver.window_handles) > 0
    except (SeleniumWebDriverException, SeleniumMaxRetryError):
        return True


def report_selenium_died(ctx: 'scr_context.ScrContext', is_err: bool = True) -> None:
    scr.log(ctx, Verbosity.ERROR if is_err else Verbosity.WARN,
            "the selenium instance was closed unexpectedly")


def report_selenium_error(ctx: 'scr_context.ScrContext', ex: Exception) -> None:
    scr.log(ctx, Verbosity.ERROR, f"critical selenium error: {str(ex)}")


def setup_selenium(ctx: 'scr_context.ScrContext') -> None:
    if ctx.repl:
        prevent_selenium_sigint()
    if ctx.selenium_variant == SeleniumVariant.TORBROWSER:
        setup_selenium_tor(ctx)
    elif ctx.selenium_variant == SeleniumVariant.CHROME:
        setup_selenium_chrome(ctx)
    else:
        assert ctx.selenium_variant == SeleniumVariant.FIREFOX
        setup_selenium_firefox(ctx)
    assert ctx.selenium_driver is not None
    if ctx.user_agent is None:
        ctx.user_agent = str(selenium_exec_script(
            ctx, "return navigator.userAgent;"))

    ctx.selenium_driver.set_page_load_timeout(ctx.request_timeout_seconds)
    if ctx.cookie_jar:
        # todo: implement something more clever for this, at least for chrome:
        # https://stackoverflow.com/questions/63220248/how-to-preload-cookies-before-first-request-with-python3-selenium-chrome-webdri
        selenium_add_cookies_through_get(ctx)
