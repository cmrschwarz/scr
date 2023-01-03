import logging
import scr.version
import sys

ANSICOLOR_BLACK = "\x1B[30m"
ANSICOLOR_RED = "\x1B[31m"
ANSICOLOR_GREEN = "\x1B[32m"
ANSICOLOR_YELLOW = "\x1B[33m"
ANSICOLOR_BLUE = "\x1B[34m"
ANSICOLOR_MAGENTA = "\x1B[35m"
ANSICOLOR_CYAN = "\x1B[36m"
ANSICOLOR_WHITE = "\x1B[37m"
ANSICOLOR_BOLD = "\x1B[1m"
ANSICOLOR_CLEAR = "\x1B[0m"


class ScrLogFormatter(logging.Formatter):
    custom_level_formatters: dict[int, logging.Formatter]

    def __init__(self, ansi_colors: bool) -> None:
        super().__init__(fmt="[%(levelname)s]: %(message)s")
        levels = {
            logging.DEBUG: ("[DEBUG]: ", ANSICOLOR_MAGENTA),
            logging.INFO:  ("[INFO]:  ", ANSICOLOR_CYAN),
            logging.WARN:  ("[WARN]:  ", ANSICOLOR_YELLOW),
            logging.ERROR: ("[ERROR]: ", ANSICOLOR_RED),
            logging.FATAL: ("[FATAL]: ", ANSICOLOR_BOLD + ANSICOLOR_RED),
        }
        self.custom_level_formatters = {}
        for lvl, (name, color) in levels.items():
            fmt = name + "%(message)s"
            if ansi_colors:
                fmt = color + fmt + ANSICOLOR_CLEAR
            self.custom_level_formatters[lvl] = logging.Formatter(fmt)

        self.default_formatter = logging.Formatter("")

    def format(self, record: logging.LogRecord) -> str:
        if record.levelno in self.custom_level_formatters:
            return self.custom_level_formatters[record.levelno].format(record)
        return super().format(record)


SCR_LOG = logging.getLogger(scr.version.SCR_NAME)
SCR_LOG.setLevel(logging.DEBUG)
SCR_LOG_STREAM = logging.StreamHandler()
SCR_LOG_STREAM.setLevel(logging.DEBUG)
SCR_LOG_STREAM.setFormatter(ScrLogFormatter(sys.platform != "win32" and sys.stderr.isatty()))
SCR_LOG.addHandler(SCR_LOG_STREAM)
