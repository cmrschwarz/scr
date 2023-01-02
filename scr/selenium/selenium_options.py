from enum import Enum


class SeleniumVariant(Enum):
    DISABLED = 0
    CHROME = 1
    FIREFOX = 2
    TORBROWSER = 3

    @staticmethod
    def default_unless_disabled() -> 'SeleniumVariant':
        return SeleniumVariant.FIREFOX

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


class SeleniumPageAcceptance(Enum):
    # accept the document once selenium reports it as 'loaded'
    PLAIN = 0
    # accept the document once it reaches any accepting transform
    # (like dl, w, p, in, or acc)
    ANY_ACCEPT = 1
    # ask the user on the cli to accept the document, displaying the number
    # of matches that reached an accepting transform
    INTERACTIVE = 2
    # like interactive, but instead of throwing away matches from earlier
    # document versions, keep them around
    INTERACTIVE_CONCAT = 3
