import sys
import warnings
import os

from scr import chain_options, instance_options, result, document


def run(
    root_chain: chain_options.ChainOptions,
    docs: list[document.Document],
    opts: instance_options.InstanceOptions = instance_options.DEFAULT_INSTANCE_OPTIONS
) -> list[result.Result]:
    return []


def run_cli(args: list[str]) -> list[result.Result]:
    return []


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
