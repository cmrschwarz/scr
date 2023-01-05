from scr import chain_options, context_options, document, range_spec, chain_spec, scr_option
from typing import Optional, Any
import re


class CliArgsParseException(Exception):
    arg_ref: tuple[int, str]

    def __init__(self, arg_ref: tuple[int, str], *args: Any) -> None:
        super().__init__(*args)
        self.arg_ref = arg_ref


def print_help() -> None:
    print("")  # TODO


def try_parse_as_context_opt(
    ctx_opts: 'context_options.ContextOptions',
    argname: str,
    value: str,
    arg_ref: tuple[int, str]
) -> bool:
    if argname in ["--help", "-h"]:
        ctx_opts.print_help.set(True, arg_ref)
        return True
    if argname == "--version":
        ctx_opts.print_version.set(True, arg_ref)
        return True
    return False


def try_parse_as_doc(
    docs: list['document.Document'],
    argname: str,
    value: str,
    chains: list['chain_options.ChainOptions'],
    arg_ref: tuple[int, str]
) -> bool:
    return False


def try_parse_as_chain_opt(
        rc: 'chain_options.ChainOptions',
        argname: str,
        value: str,
        chains: list['chain_options.ChainOptions'],
        arg_ref: tuple[int, str]
) -> bool:
    return False


def try_parse_as_transform(
    arg: str,
    curr_chain: 'chain_options.ChainOptions',
    argname: str,
    value: str,
    chains: list['chain_options.ChainOptions'],
    arg_ref: tuple[int, str]
) -> tuple[bool, 'chain_options.ChainOptions']:
    return False, curr_chain


CLI_ARG_REGEX = re.compile("(?P<argname>[a-zA-Z_]+)(?P<chainspec>[/0-9a-zA-Z-^]*)(=(?P<value>.*))?")


def parse(args: list[str]) -> tuple[chain_options.ChainOptions, list[document.Document], context_options.ContextOptions]:
    root_chain = chain_options.ChainOptions()
    docs: list[document.Document] = []
    ctx_opts = context_options.ContextOptions()
    curr_chain = root_chain

    try:
        for i, arg in enumerate(args[1:]):
            arg_ref = (i + 1, arg)
            m = CLI_ARG_REGEX.match(arg)
            if m is None:
                raise CliArgsParseException(arg_ref, "invalid argument")
            argname = m["argname"]
            chainspec = m["chainspec"]
            value = m["value"]
            if chainspec:
                chains = list(chain_spec.parse_chain_spec(chainspec).instantiate(curr_chain))
            else:
                chains = [curr_chain]
            if try_parse_as_context_opt(ctx_opts, argname, value, arg_ref):
                if chainspec:
                    raise CliArgsParseException(arg_ref, f"cannot specify chain range for global argument")
                continue
            if try_parse_as_doc(docs, argname, value, chains, arg_ref):
                continue
            if try_parse_as_chain_opt(root_chain, argname, value, chains, arg_ref):
                continue
            success, curr_chain = try_parse_as_transform(arg, curr_chain, argname, value, chains, arg_ref)
            if success:
                continue
            raise CliArgsParseException(arg_ref, f"unknown argument")
    except scr_option.ScrOptionReassignmentError as ex:
        pass
    return (root_chain, docs, ctx_opts)
