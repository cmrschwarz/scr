import sys
import warnings
import os
import shlex
from typing import Optional
from scr import chain_options, context_options, context, document, match, cli_args, chain, process_documents
from scr.selenium import selenium_updater
from scr.version import SCR_VERSION, SCR_NAME
from scr.logger import SCR_LOG
from scr.transforms import transform


def perform_side_tasks(opts: 'context_options.ContextOptions') -> None:
    for sv in opts.install_selenium_drivers.get_all():
        selenium_updater.install_selenium_driver(sv)

    for sv in opts.install_selenium_drivers.get_all():
        selenium_updater.update_selenium_driver(sv)

    if opts.print_help.get_or_default(context_options.DEFAULT_CONTEXT_OPTIONS.print_help.get()):
        cli_args.print_help()

    if opts.print_version.get_or_default(context_options.DEFAULT_CONTEXT_OPTIONS.print_version.get()):
        print(SCR_VERSION)


def run_repl(
    ctx: 'context.Context',
    rc: 'chain.Chain',
    docs: list['document.Document'],
    initial_args: Optional[list[str]]
) -> list['match.Match']:
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
            context_options.update_context(ctx, opts)
            chain_options.update_chain(rc, root_chain)
            process_documents.process_documents(ctx, rc, docs)
        except KeyboardInterrupt:
            print("")
            continue


def run(
    root_chain: 'chain_options.ChainOptions',
    docs: list['document.Document'],
    opts: Optional['context_options.ContextOptions'] = None,
    initial_args: Optional[list[str]] = None
) -> list['match.Match']:
    if opts is None:
        opts = context_options.DEFAULT_CONTEXT_OPTIONS
    perform_side_tasks(opts)
    ctx = context_options.create_context(opts)
    rc = chain_options.create_root_chain(root_chain, ctx)
    chain.validate_chain_tree(rc)
    try:
        if opts.repl.get_or_default(context_options.DEFAULT_CONTEXT_OPTIONS.repl.get()):
            return run_repl(ctx, rc, docs, initial_args)
        return process_documents.process_documents(ctx, rc, docs)
    finally:
        ctx.finalize()


def run_cli(args: list[str]) -> list['match.Match']:
    (root_chain, docs, opts) = cli_args.parse(args)
    return run(root_chain, docs, opts)


def main() -> None:
    try:
        # to silence: "Setting a profile has been deprecated" on launching tor
        warnings.filterwarnings(
            "ignore", module=".*selenium.*", category=DeprecationWarning
        )
        try:
            run_cli(sys.argv)
        except (cli_args.CliArgsParseException, chain.ChainValidationException, transform.TransformApplicationError) as ex:
            SCR_LOG.error(str(ex))
        sys.exit(0)
    except BrokenPipeError:
        # Python flushes standard streams on exit; redirect remaining output
        # to devnull to avoid another BrokenPipeError at shutdown
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(1)
