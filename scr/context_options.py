from scr.scr_option import ScrOption, ScrOptionSet
from scr.selenium import selenium_options
from scr import context, progress_report
from typing import Optional
import multiprocessing


class ContextOptions:
    parallel_jobs: ScrOption[int]
    progress_report: ScrOption[bool]
    install_selenium_drivers: ScrOptionSet['selenium_options.SeleniumVariant']
    update_selenium_drivers: ScrOptionSet['selenium_options.SeleniumVariant']
    repl: ScrOption[bool]
    exit_repl: ScrOption[bool]
    print_help: ScrOption[bool]
    print_version: ScrOption[bool]

    def __init__(
        self,
        parallel_jobs: Optional[int] = None,
        progress_report: Optional[bool] = None,
        install_selenium_drivers: Optional[set['selenium_options.SeleniumVariant']] = None,
        update_selenium_drivers: Optional[set['selenium_options.SeleniumVariant']] = None,
        repl: Optional[bool] = None,
        exit_repl: Optional[bool] = None,
        print_help: Optional[bool] = None,
        print_version: Optional[bool] = None,
    ) -> None:
        self.parallel_jobs = ScrOption(parallel_jobs)
        self.progress_report = ScrOption(progress_report)
        self.install_selenium_drivers = ScrOptionSet(install_selenium_drivers)
        self.update_selenium_drivers = ScrOptionSet(update_selenium_drivers)
        self.repl = ScrOption(repl)
        self.exit_repl = ScrOption(exit_repl)
        self.print_help = ScrOption(print_help)
        self.print_version = ScrOption(print_version)


DEFAULT_CONTEXT_OPTIONS = ContextOptions(
    parallel_jobs=2,  # multiprocessing.cpu_count(),
    progress_report=True,
    install_selenium_drivers=None,
    update_selenium_drivers=None,
    repl=False,
    exit_repl=False,
    print_help=False,
    print_version=False
)


def create_context(opts: ContextOptions) -> 'context.Context':
    return context.Context(
        opts.parallel_jobs.get_or_default(DEFAULT_CONTEXT_OPTIONS.parallel_jobs.get()),
        opts.progress_report.get_or_default(DEFAULT_CONTEXT_OPTIONS.progress_report.get()),
    )


def update_context(ctx: 'context.Context', opts: ContextOptions) -> None:
    if opts.parallel_jobs.is_set():
        ctx.set_parallel_job_count(opts.parallel_jobs.get())
    if opts.progress_report.is_set():
        pr = opts.progress_report.get()
        if ctx.progress_reporter is None and pr:
            ctx.progress_reporter = progress_report.ProgressReporter()
        elif ctx.progress_reporter is not None and not pr:
            ctx.progress_reporter = None
