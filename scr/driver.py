import sys
import warnings
import os
import shlex
from typing import Optional
from scr.chain_options import ChainOptions, create_root_chain, update_chain
from scr.context import Context
from scr.context_options import ContextOptions, DEFAULT_CONTEXT_OPTIONS, create_context, update_context
from scr.document import Document
from scr.result import Result
from scr import cli_args
from scr.selenium import selenium_updater
from scr.version import SCR_VERSION, SCR_NAME
from scr.logger import SCR_LOG


def perform_side_tasks(opts: ContextOptions) -> None:
    for sv in opts.install_selenium_drivers.get_all():
        selenium_updater.install_selenium_driver(sv)

    for sv in opts.install_selenium_drivers.get_all():
        selenium_updater.update_selenium_driver(sv)

    if opts.print_help.get_or_default(DEFAULT_CONTEXT_OPTIONS.print_help.get()):
        cli_args.print_help()

    if opts.print_version.get_or_default(DEFAULT_CONTEXT_OPTIONS.print_version.get()):
        print(SCR_VERSION)


def run_repl(ctx: Context, initial_args: Optional[list[str]]) -> list[Result]:
    if sys.platform == 'win32':
        from pyreadline3 import Readline
        readline: Readline = Readline()
    else:
        import readline
    tty = sys.stdout.isatty()
    if initial_args is not None:
        readline.add_history(shlex.join(initial_args))
    while True:
        try:
            try:
                line = input(f"{SCR_NAME}> " if tty else "").strip()
                if line:
                    readline.add_history(line)
            except EOFError:
                if tty:
                    print("")
                return []
            try:
                args = shlex.split(line)
            except ValueError as ex:
                SCR_LOG.error("malformed arguments: " + str(ex))
                continue
            if not len(args):
                continue
            try:
                (root_chain, docs, opts) = cli_args.parse(args)
            except ValueError as ex:
                SCR_LOG.error(str(ex))
                continue
            update_context(ctx, opts)
            update_chain(ctx.root_chain, root_chain)
            ctx.run(ctx.root_chain, docs)
        except KeyboardInterrupt:
            print("")
            continue


def run(
    root_chain: ChainOptions,
    docs: list[Document],
    opts: ContextOptions = DEFAULT_CONTEXT_OPTIONS,
    initial_args: Optional[list[str]] = None
) -> list[Result]:
    perform_side_tasks(opts)
    ctx = create_context(opts)
    rc = create_root_chain(root_chain, ctx)
    try:
        if opts.repl.get_or_default(DEFAULT_CONTEXT_OPTIONS.repl.get()):
            return run_repl(ctx, initial_args)
        return ctx.run(rc, docs)
    finally:
        ctx.finalize()


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
