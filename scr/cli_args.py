from scr import chain_options, context_options, document, chain_spec, scr_option, version
from scr.transforms import transform, transform_catalog
from typing import Iterable, Optional, Any
import re


class CliArgsParseException(Exception):
    arg_ref: tuple[int, str]

    def __init__(self, arg_ref: tuple[int, str], *args: Any) -> None:
        super().__init__(*args)
        self.arg_ref = arg_ref


def print_help() -> None:
    print(f"{version.SCR_NAME} [OPTIONS]")  # TODO


def str_prefixes(str: str) -> list[str]:
    return [str[:i] for i in range(len(str), 0, -1)]


TRUE_INDICATING_STRINGS = set([*str_prefixes("true"), *str_prefixes("yes"), "1"])
FALSE_INDICATING_STRINGS = set([*str_prefixes("false"), *str_prefixes("no"), "0"])


def try_parse_bool(val: str, arg_ref: tuple[int, str]) -> bool:
    if val in TRUE_INDICATING_STRINGS:
        return True
    if val in FALSE_INDICATING_STRINGS:
        return False
    raise CliArgsParseException(arg_ref, "failed to parse as bool")


def try_parse_bool_or_default(val: Optional[str], default: bool, arg_ref: tuple[int, str]) -> bool:
    if val is None:
        return default
    return try_parse_bool(val, arg_ref)


def try_parse_as_context_opt(
    ctx_opts: 'context_options.ContextOptions',
    argname: str,
    label: Optional[str],
    value: Optional[str],
    has_chainspec: bool,
    arg_ref: tuple[int, str]
) -> bool:
    matched = False
    if argname in ["--help", "-h"]:
        ctx_opts.print_help.set(True, arg_ref)
        matched = True
    elif argname == "--version":
        ctx_opts.print_version.set(True, arg_ref)
        matched = True
    elif "help".startswith(argname):
        ctx_opts.print_help.set(try_parse_bool_or_default(value, True, arg_ref), arg_ref)
        matched = True
    elif "version".startswith(argname):
        ctx_opts.print_version.set(try_parse_bool_or_default(value, True, arg_ref), arg_ref)
        matched = True
    if matched and has_chainspec:
        raise CliArgsParseException(arg_ref, f"cannot specify chain range for global argument")
    return matched


def try_parse_as_doc(
    docs: list['document.Document'],
    argname: str,
    label: Optional[str],
    value: Optional[str],
    chains: list['chain_options.ChainOptions'],
    arg_ref: tuple[int, str]
) -> bool:
    return False


def try_parse_as_chain_opt(
    co: 'chain_options.ChainOptions',
    argname: str,
    label: Optional[str],
    value: Optional[str],
    chains: list['chain_options.ChainOptions'],
    arg_ref: tuple[int, str]
) -> bool:
    return False


def try_parse_as_transform(
    curr_chain: 'chain_options.ChainOptions',
    argname: str,
    label: Optional[str],
    value: Optional[str],
    chains: list['chain_options.ChainOptions'],
    arg_ref: tuple[int, str]
) -> tuple[bool, 'chain_options.ChainOptions']:
    for tf in transform_catalog.TRANSFORM_CATALOG:
        if tf.name_matches(argname):
            if label is None:
                label = argname
            try:
                tf_inst = tf.create(label, value)
            except transform.TransformValueError as ex:
                raise CliArgsParseException(arg_ref, *ex.args)
            for c in chains:
                c.transforms.append(tf_inst)
            next_chain = tf_inst.get_next_chain(curr_chain)
            assert isinstance(next_chain, chain_options.ChainOptions)
            return True, next_chain
    return False, curr_chain


CLI_ARG_REGEX = re.compile("(?P<argname>[a-zA-Z_]+)(@(?P<label>[a-zA-Z_]+))?(?P<chainspec>[/0-9a-zA-Z-^]+)?(=(?P<value>.*))?")


def parse(args: list[str]) -> tuple[chain_options.ChainOptions, list[document.Document], context_options.ContextOptions]:
    root_chain = chain_options.ChainOptions()
    docs: list[document.Document] = []
    ctx_opts = context_options.ContextOptions()
    curr_chain = root_chain

    try:
        for i, arg in enumerate(args[1:]):
            arg_ref = (i + 1, arg)
            if arg.startswith("-"):
                if try_parse_as_context_opt(ctx_opts, arg, None, None, False, arg_ref):
                    continue
            m = CLI_ARG_REGEX.match(arg)
            if m is None:
                raise CliArgsParseException(arg_ref, "invalid argument")
            argname = m.group("argname")
            label = m.group("label")
            chainspec = m.group("chainspec")
            value = m.group("value")
            if chainspec is not None:
                chains = list(chain_spec.parse_chain_spec(chainspec).instantiate(curr_chain))
            else:
                chains = [curr_chain]
            if try_parse_as_context_opt(ctx_opts, argname, label, value, chainspec is not None, arg_ref):
                continue
            if try_parse_as_doc(docs, argname, label, value, chains, arg_ref):
                continue
            if try_parse_as_chain_opt(root_chain, argname, label, value, chains, arg_ref):
                continue
            success, curr_chain = try_parse_as_transform(curr_chain, argname, label, value, chains, arg_ref)
            if success:
                continue
            raise CliArgsParseException(arg_ref, f"unknown argument")
    except scr_option.ScrOptionReassignmentError as ex:
        pass
    return (root_chain, docs, ctx_opts)
