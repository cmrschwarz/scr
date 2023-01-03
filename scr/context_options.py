from scr.scr_option import ScrOption, ScrOptionSet
from scr.selenium import selenium_options
from scr import context, chain, document
from typing import Optional
import multiprocessing


class ContextOptions:
    parallel_jobs: ScrOption[int]
    progress_report: ScrOption[bool]
    install_selenium_drivers: ScrOptionSet['selenium_options.SeleniumVariant']
    update_selenium_drivers: ScrOptionSet['selenium_options.SeleniumVariant']
    repl: ScrOption[bool]
    print_help: ScrOption[bool]
    print_version: ScrOption[bool]

    def __init__(
        self,
        parallel_jobs: Optional[int] = None,
        progress_report: Optional[bool] = None,
        install_selenium_drivers: Optional[set['selenium_options.SeleniumVariant']] = None,
        update_selenium_drivers: Optional[set['selenium_options.SeleniumVariant']] = None,
        repl: Optional[bool] = False,
        print_help: Optional[bool] = None,
        print_version: Optional[bool] = None,
    ) -> None:
        self.parallel_jobs = ScrOption(parallel_jobs)
        self.progress_report = ScrOption(progress_report)
        self.install_selenium_drivers = ScrOptionSet(install_selenium_drivers)
        self.update_selenium_drivers = ScrOptionSet(update_selenium_drivers)
        self.print_help = ScrOption(print_help)
        self.print_version = ScrOption(print_version)


DEFAULT_CONTEXT_OPTIONS = ContextOptions(
    parallel_jobs=multiprocessing.cpu_count(),
    progress_report=True,
    install_selenium_drivers=None,
    update_selenium_drivers=None,
    print_help=False,
    print_version=True
)


def create_context(opts: ContextOptions) -> 'context.Context':
    return context.Context(
        opts.parallel_jobs.get_or_default(DEFAULT_CONTEXT_OPTIONS.parallel_jobs.get()),
        opts.progress_report.get_or_default(DEFAULT_CONTEXT_OPTIONS.progress_report.get()),
    )


def update_context(opts: ContextOptions, prev: 'context.Context') -> 'context.Context':
    raise NotImplementedError
