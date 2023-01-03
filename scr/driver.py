import sys
import warnings
import os

from scr.chain_options import ChainOptions, create_chain, update_root_chain
from scr.context import Context
from scr.context_options import ContextOptions, DEFAULT_CONTEXT_OPTIONS, create_context
from scr.document import Document
from scr.result import Result
from scr import cli_args
from scr.selenium import selenium_updater
from scr.version import SCR_VERSION


def perform_side_tasks(opts: ContextOptions) -> None:
    for sv in opts.install_selenium_drivers.get_all():
        selenium_updater.install_selenium_driver(sv)

    for sv in opts.install_selenium_drivers.get_all():
        selenium_updater.update_selenium_driver(sv)

    if opts.print_help.get_or_default(DEFAULT_CONTEXT_OPTIONS.print_help.get()):
        cli_args.print_help()

    if opts.print_version.get_or_default(DEFAULT_CONTEXT_OPTIONS.print_version.get()):
        print(SCR_VERSION)


def run_repl(ctx: Context) -> list[Result]:
    raise NotImplementedError


def run(
    root_chain: ChainOptions,
    docs: list[Document],
    opts: ContextOptions = DEFAULT_CONTEXT_OPTIONS
) -> list[Result]:
    perform_side_tasks(opts)
    ctx = create_context(opts)
    rc = create_chain(root_chain, ctx)
    if opts.repl.get_or_default(DEFAULT_CONTEXT_OPTIONS.repl.get()):
        return run_repl(ctx)
    return ctx.run(rc, docs)


def run_cli(args: list[str]) -> list[Result]:
    (root_chain, docs, opts) = cli_args.parse(args)
    return run(root_chain, docs, opts)


def main() -> None:
    try:
        # to silence: "Setting a profile has been deprecated" on launching tor
        warnings.filterwarnings(
            "ignore", module=".*selenium.*", category=DeprecationWarning
        )
        run_cli(sys.argv)
        sys.exit(0)
    except BrokenPipeError:
        # Python flushes standard streams on exit; redirect remaining output
        # to devnull to avoid another BrokenPipeError at shutdown
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(1)
