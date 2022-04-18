from .definitions import (
    SeleniumVariant, Verbosity, ScrSetupError, selenium_variants_display_dict,
    SCRIPT_NAME
)
from . import scr, utils, scr_context, windows
from typing import Optional, cast
import selenium_driver_updater

import selenium_driver_updater.util.exceptions
import os
import glob
import distutils.spawn
from functools import cache
SELENIUM_DRIVER_DIR_ADDED_TO_PATH: bool = False


def try_resolve_executable_names(exec_names: list[str]) -> Optional[str]:
    for x in exec_names:
        path = distutils.spawn.find_executable(x)
        if path is not None:
            return path
    return None


def accept_first_existing_path(paths: list[str]) -> Optional[str]:
    for path in paths:
        if os.path.exists(path):
            return path
    return None


def find_chrome_binary() -> Optional[str]:
    if utils.is_linux():
        return try_resolve_executable_names([
            "chromium",
            "chromium-browser",
            "google-chrome-stable",
            "google-chrome"
        ])
    if utils.is_osx():
        return accept_first_existing_path([
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        ])
    if not utils.is_windows():
        return None

    return utils.choose_first_not_none(
        lambda: windows.try_get_app_path_from_reg_uninstall_path("Chromium", "chrome.exe"),
        lambda: windows.try_get_app_path_from_reg_start_menu_internet("Chromium"),
        lambda: windows.try_get_app_path_from_reg_app_paths("chrome.exe"),
        lambda: windows.try_get_app_path_from_reg_uninstall_path("Google Chrome", "chrome.exe"),
        lambda: windows.try_get_app_path_from_reg_start_menu_internet("Google Chrome"),
    )


@ cache
def get_script_dir() -> str:
    return os.path.abspath(os.path.dirname(__file__))


@ cache
def get_selenium_drivers_dir() -> str:
    script_dir = get_script_dir()
    debug_path = os.path.join(script_dir, "selenium_drivers_debug")
    if os.path.exists(debug_path):
        return debug_path
    return os.path.join(get_script_dir(), "selenium_drivers")


def get_selenium_driver_executable_basename(variant: SeleniumVariant) -> Optional[str]:
    bn = {
        SeleniumVariant.CHROME: "chromedriver",
        SeleniumVariant.FIREFOX: "geckodriver",
        SeleniumVariant.TORBROWSER: "geckodriver",
        SeleniumVariant.DISABLED: None
    }[variant]
    if bn is None:
        return None
    return bn + (".exe" if utils.is_windows() else "")


def get_local_selenium_driver_executable_path(variant: SeleniumVariant) -> Optional[str]:
    basename = get_selenium_driver_executable_basename(variant)
    if basename is None:
        return None
    return os.path.join(
        get_selenium_drivers_dir(),
        basename
    )


def touch_file(path: str) -> None:
    open(path, "ab+").close()


def is_selenium_driver_present(path: str) -> bool:
    try:
        return os.path.getsize(path) != 0
    except FileNotFoundError:
        try:
            touch_file(path)
        except IOError:
            pass
        return False


def try_get_local_selenium_driver_path(variant: 'SeleniumVariant') -> Optional[str]:
    path = get_local_selenium_driver_executable_path(variant)
    if path is None:
        return None
    if is_selenium_driver_present(path):
        return path
    return None


def put_local_selenium_driver_in_path(ctx: 'scr_context.ScrContext', variant: 'SeleniumVariant') -> None:
    global SELENIUM_DRIVER_DIR_ADDED_TO_PATH
    if SELENIUM_DRIVER_DIR_ADDED_TO_PATH:
        return
    SELENIUM_DRIVER_DIR_ADDED_TO_PATH = True
    path_seperator = ":" if not utils.is_windows() else ";"
    os.environ["PATH"] += path_seperator + get_selenium_drivers_dir()
    scr.log(ctx, Verbosity.INFO, f"added to PATH: {get_selenium_drivers_dir()}")


def get_preferred_selenium_driver_path(variant: 'SeleniumVariant') -> str:
    path = try_get_local_selenium_driver_path(variant)
    if path is not None:
        return path
    basename = get_selenium_driver_executable_basename(variant)
    # this function makes no sense for DISABLED
    assert basename is not None
    return basename


def install_selenium_driver(ctx: 'scr_context.ScrContext', variant: 'SeleniumVariant', update: bool) -> None:
    if variant == SeleniumVariant.CHROME:
        driver_name = selenium_driver_updater.DriverUpdater.chromedriver
    elif variant in [SeleniumVariant.FIREFOX, SeleniumVariant.TORBROWSER]:
        driver_name = selenium_driver_updater.DriverUpdater.geckodriver
    else:
        raise ScrSetupError(
            "unable to install webdriver for '{selenium_variants_display_dict[variant]}'"
        )
    driver_dir = get_selenium_drivers_dir()
    local_driver_path = cast(
        str, get_local_selenium_driver_executable_path(variant)
    )
    have_local = is_selenium_driver_present(local_driver_path)
    if have_local and not update:
        scr.log(
            ctx, Verbosity.INFO,
            f"existing {selenium_variants_display_dict[variant]} driver found"
        )
        return
    success = False

    try:
        scr.log(
            ctx, Verbosity.INFO,
            ("updating" if have_local else "installing") +
            f" {selenium_variants_display_dict[variant]} driver ..."
        )
        selenium_driver_updater.DriverUpdater.install(
            path=driver_dir, driver_name=driver_name,
            check_driver_is_up_to_date=have_local,
            enable_library_update_check=False,
            upgrade=True,
            info_messages=False
        )
        success = True
        scr.log(
            ctx, Verbosity.INFO,
            f"{selenium_variants_display_dict[variant]} driver "
            + ("updated" if have_local else "installed")
        )
    except (selenium_driver_updater.util.exceptions.Error) as ex:
        scr.log(
            ctx, Verbosity.ERROR,
            f"failed to fetch {selenium_variants_display_dict[variant]} driver: {str(ex)}"
        )
    finally:
        # we should not have to do this, this is working around a bug in the library
        if not success:
            open(local_driver_path, "w").close()
        # cleanup_selenium_installation_artifacts(ctx, silent=not success)


def cleanup_selenium_installation_artifacts(ctx: 'scr_context.ScrContext', silent: bool = False) -> None:
    # clean up remains from potentially failed installs
    present_files = [
        os.path.abspath(p)
        for p in glob.glob(get_selenium_drivers_dir() + "/**")
    ]
    variant_files = {
        get_local_selenium_driver_executable_path(v)
        for v in SeleniumVariant if v is not None
    }
    cleanup = False
    for pf in present_files:
        if pf not in variant_files:
            os.remove(pf)
            cleanup = True
    if cleanup:
        scr.log(
            ctx, Verbosity.INFO,
            "cleaned up artifacts from previous installations"
        )


def uninstall_selenium_driver(ctx: 'scr_context.ScrContext', variant: 'SeleniumVariant') -> None:
    cleanup_selenium_installation_artifacts(ctx)
    path = try_get_local_selenium_driver_path(variant)
    if path is None:
        scr.log(
            ctx, Verbosity.WARN,
            f"no {selenium_variants_display_dict[variant]} driver (local to {SCRIPT_NAME}) installed"
        )
        return
    open(path, 'w').close()
    scr.log(
        ctx, Verbosity.INFO,
        f"{selenium_variants_display_dict[variant]} driver uninstalled"
    )
