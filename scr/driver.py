import sys
import warnings
import os

from scr import chain_options, context_options, result, document, parse_cli_args


def run(
    root_chain: chain_options.ChainOptions,
    docs: list[document.Document],
    opts: context_options.ContextOptions = context_options.DEFAULT_INSTANCE_OPTIONS
) -> list[result.Result]:
    return []


def run_cli(args: list[str]) -> list[result.Result]:
    (root_chain, docs, opts) = parse_cli_args.parse(args)
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
