from enum import Enum
from typing import Optional
from scr import utils


class SeleniumVariant(Enum):
    DISABLED = 0
    FIREFOX = 1
    CHROME = 2
    CHROMIUM = 3
    TORBROWSER = 4
    DEFAULT = 999

    @staticmethod
    def default_unless_disabled() -> 'SeleniumVariant':
        return SeleniumVariant.FIREFOX

    @staticmethod
    def try_parse(val: str) -> Optional['SeleniumVariant']:
        for sv in SeleniumVariant:
            if sv.name.lower().startswith(val):
                return sv

        b = utils.try_parse_bool(val)
        if b is False:
            return SeleniumVariant.DISABLED
        if b is True:
            return SeleniumVariant.DEFAULT
        return None

    def enabled(self) -> bool:
        return self != SeleniumVariant.DISABLED


class SeleniumDownloadStrategy(Enum):
    # scr itself just generates a web request
    # (with the appropriate cookies extracted from the seleinum context)
    # most robust, but in case of tor selenium,
    # may be routed through a different tor circuit, causing it to fail
    SCR = 0
    # insert hidden download button on the page and 'click' it
    # does not work for cross origin downloads
    BROWSER = 1
    # use the javascript fetch api and give the base64 encoded
    # result back to scr (high ram usage for large files)
    JAVASCRIPT = 2

    @staticmethod
    def try_parse(val: str) -> Optional['SeleniumDownloadStrategy']:
        for sds in SeleniumDownloadStrategy:
            if sds.name.lower().startswith(val):
                return sds
        if "js" == val:
            return SeleniumDownloadStrategy.JAVASCRIPT
        return None
