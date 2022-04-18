import sys
from typing import Optional
from enum import Enum
import os
import shlex
if sys.platform == 'win32':
    import win32api
    import win32event
    import win32file
    import pywintypes
    import winreg
    WOW64_KEYS: list[int] = [0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_64KEY]
else:
    WOW64_KEYS: list[int] = []


class RegistryClass(Enum):
    if sys.platform == 'win32':
        HKEY_CLASSES_ROOT = winreg.HKEY_CLASSES_ROOT
        HKEY_CURRENT_USER = winreg.HKEY_CURRENT_USER
        HKEY_LOCAL_MACHINE = winreg.HKEY_LOCAL_MACHINE
        HKEY_USERS = winreg.HKEY_USERS
        HKEY_PERFORMANCE_DATA = winreg.HKEY_PERFORMANCE_DATA
        HKEY_CURRENT_CONFIG = winreg.HKEY_CURRENT_CONFIG
        HKEY_DYN_DATA = winreg.HKEY_DYN_DATA
    else:
        HKEY_CLASSES_ROOT = 0
        HKEY_CURRENT_USER = 1
        HKEY_LOCAL_MACHINE = 2
        HKEY_USERS = 3
        HKEY_PERFORMANCE_DATA = 4
        HKEY_CURRENT_CONFIG = 5
        HKEY_DYN_DATA = 6


def stdin_has_content(timeout: float) -> bool:
    if sys.platform != 'win32':
        return False
    else:
        try:
            # without this the wait sometimes returns without there being
            # any actual data -> we woul block infinitely on the read
            win32file.FlushFileBuffers(win32api.STD_INPUT_HANDLE)
        except pywintypes.error:
            # the flush sometimes fails, too bad!
            pass
        return win32event.WaitForSingleObject(
            win32api.STD_INPUT_HANDLE, int(timeout * 1000)  # milliseconds
        ) is win32event.WAIT_OBJECT_0


def get_registry_entries(
    rc: RegistryClass,
    registry_path: str, values: list[Optional[str]] = [None],
    wow_key: int = 0
) -> Optional[list[Optional[str]]]:
    if sys.platform != 'win32':
        return None
    else:
        results: list[Optional[str]] = []
        key = None
        try:
            key = winreg.OpenKey(rc.value, registry_path, 0, winreg.KEY_READ | wow_key)
            for subkey in values:
                try:
                    # subkey may be None, which is legal in winapi (returns value of the key itself)
                    # but for some reason forbidden by the type annotation in winreg
                    value = winreg.QueryValueEx(key, subkey)[0] # type: ignore
                    results.append(value)
                except FileNotFoundError:
                    results.append(None)
            return results
        except FileNotFoundError:
            return [None] * len(values)
        finally:
            if key is not None:
                winreg.CloseKey(key)


def get_registry_entries_anywow(
    rcs: list[RegistryClass],
    key: str,
    values: list[Optional[str]] = [None],
    wow_keys: list[int] = WOW64_KEYS
) -> list[Optional[str]]:
    for rc in rcs:
        for wowkey in wow_keys:
            res = get_registry_entries(rc, key, values, wowkey)
            if res is not None:
                if any(r is not None for r in res):
                    return res
    return [None] * len(wow_keys)


def try_get_app_path_from_reg_uninstall_path(app_name: str, app_exe_name: str) -> Optional[str]:
    install_loc = get_registry_entries_anywow(
        [RegistryClass.HKEY_LOCAL_MACHINE, RegistryClass.HKEY_CURRENT_USER],
        "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + app_name,
        ["InstallLocation"]
    )[0]
    if install_loc is not None:
        loc = os.path.join(install_loc, app_exe_name)
        if os.path.exists(loc):
            return loc
    return None


def try_get_app_path_from_reg_start_menu_internet(app_name: str) -> Optional[str]:
    command = get_registry_entries_anywow(
        [RegistryClass.HKEY_LOCAL_MACHINE, RegistryClass.HKEY_CURRENT_USER],
        "SOFTWARE\\Clients\\StartMenuInternet\\" + app_name + "\\shell\\open\\command"
    )[0]
    if command is not None:
        app_path = shlex.split(command)[0]
        if os.path.exists(app_path):
            return app_path
    return None


def try_get_app_path_from_reg_app_paths(app_exe_name: str) -> Optional[str]:
    app_path = get_registry_entries_anywow(
        [RegistryClass.HKEY_LOCAL_MACHINE, RegistryClass.HKEY_CURRENT_USER],
        "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + app_exe_name,
    )[0]
    if app_path is not None and os.path.exists(app_path):
        return app_path
    return None
