from scr.scr_option import ScrOption, ScrOptionSet
from typing import Optional
import multiprocessing


class ContextOptions:
    progress_report: ScrOption[bool]
    parallel_jobs: ScrOption[int]
    print_help: ScrOption[bool]
    update_selenium_drivers: ScrOptionSet[str]
    install_selenium_drivers: ScrOptionSet[str]

    def __init__(
        self,
        progress_report: Optional[bool] = None,
        parallel_jobs: Optional[int] = None,
        print_help: Optional[bool] = None,
        update_selenium_drivers: Optional[set[str]] = None,
        install_selenium_drivers: Optional[set[str]] = None,
    ) -> None:
        self.progress_report = ScrOption(progress_report)
        self.parallel_jobs = ScrOption(parallel_jobs)
        self.print_help = ScrOption(print_help)
        self.update_selenium_drivers = ScrOptionSet(update_selenium_drivers)
        self.install_selenium_drivers = ScrOptionSet(install_selenium_drivers)


DEFAULT_CONTEXT_OPTIONS = ContextOptions(
    progress_report=True,
    parallel_jobs=multiprocessing.cpu_count(),
    print_help=False,
    update_selenium_drivers=None,
    install_selenium_drivers=None
)
