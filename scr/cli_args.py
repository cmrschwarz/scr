from scr import chain_options, context_options, document, chain_spec, scr_option, version
from scr.transforms import transform, transform_catalog
from scr.selenium import selenium_options
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


def try_parse_bool(val: str) -> Optional[bool]:
    if val in TRUE_INDICATING_STRINGS:
        return True
    if val in FALSE_INDICATING_STRINGS:
        return False
    return None


def try_parse_bool_arg_or_default(val: Optional[str], default: bool, arg_ref: tuple[int, str]) -> bool:
    if val is None:
        return default
    res = try_parse_bool(val)
    if res is None:
        raise CliArgsParseException(arg_ref, "failed to parse as bool")
    return res


def try_parse_as_context_opt(
    ctx_opts: 'context_options.ContextOptions',
    argname: str,
    label: Optional[str],
    value: Optional[str],
    chainspec: Optional[chain_spec.ChainSpec],
    arg_ref: tuple[int, str]
) -> bool:
    matched = False
    if argname in ["--help", "-h"]:
        ctx_opts.print_help.set(True, arg_ref)
        matched = True
    elif argname == "--version":
        ctx_opts.print_version.set(True, arg_ref)
        matched = True
    elif argname == "help":
        ctx_opts.print_help.set(try_parse_bool_arg_or_default(value, True, arg_ref), arg_ref)
        matched = True
    elif argname == "version":
        ctx_opts.print_version.set(try_parse_bool_arg_or_default(value, True, arg_ref), arg_ref)
        matched = True
    if matched:
        if label is not None:
            raise CliArgsParseException(arg_ref, f"cannot specify label for global argument")
        if chainspec is not None:
            raise CliArgsParseException(arg_ref, f"cannot specify chain range for global argument")
    return matched


def try_parse_as_doc(
    docs: list['document.Document'],
    argname: str,
    label: Optional[str],
    value: Optional[str],
    chainspec: Optional[chain_spec.ChainSpec],
    arg_ref: tuple[int, str]
) -> bool:
    doc_type = document.DocumentType.try_parse(argname)
    if doc_type is None:
        return False
    if label is not None:
        raise CliArgsParseException(arg_ref, f"cannot specify label for document")
    if doc_type == document.DocumentType.STDIN:
        if value is not None:
            raise CliArgsParseException(arg_ref, f"cannot specify value for stdin document")
    else:
        if value is None:
            if doc_type == document.DocumentType.STRING:
                raise CliArgsParseException(arg_ref, f"missing value for string document")
            raise CliArgsParseException(arg_ref, f"missing source for document")
    docs.append(document.Document())
    return True


def try_parse_as_chain_opt(
    co: 'chain_options.ChainOptions',
    argname: str,
    label: Optional[str],
    value: Optional[str],
    chainspec: Optional['chain_spec.ChainSpec'],
    arg_ref: tuple[int, str]
) -> bool:
    if "dte" == argname:
        if value is None:
            raise CliArgsParseException(arg_ref, "missing argument for default text encoding")
        co.default_text_encoding.set(value, arg_ref)
    elif "ppte" == argname:
        co.prefer_parent_text_encoding.set(try_parse_bool_arg_or_default(value, True, arg_ref), arg_ref)
    elif "fte" == argname:
        co.force_text_encoding.set(try_parse_bool_arg_or_default(value, True, arg_ref), arg_ref)
    elif "selenium".startswith(argname):
        if value is not None:
            sv = selenium_options.SeleniumVariant.try_parse(value)
            if sv is None:
                raise CliArgsParseException(arg_ref, "failed to parse selenium variant argument")
        else:
            sv = selenium_options.SeleniumVariant.DEFAULT
        co.selenium_variant.set
    elif "selds" == argname:
        pass
    else:
        return False
    return True


def try_parse_as_transform(
    curr_chain: 'chain_options.ChainOptions',
    argname: str,
    label: Optional[str],
    value: Optional[str],
    chainspec: Optional['chain_spec.ChainSpec'],
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
            if chainspec is None:
                curr_chain.transforms.append(tf_inst)
            else:
                for c in chainspec.instantiate(curr_chain):
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
                if try_parse_as_context_opt(ctx_opts, arg, None, None, None, arg_ref):
                    continue
            m = CLI_ARG_REGEX.match(arg)
            if m is None:
                raise CliArgsParseException(arg_ref, "invalid argument")
            argname = m.group("argname")
            label = m.group("label")
            chainspec = m.group("chainspec")
            chainspec = chain_spec.parse_chain_spec(chainspec) if chainspec is not None else None
            value = m.group("value")
            succ_ctx = try_parse_as_context_opt(ctx_opts, argname, label, value, chainspec, arg_ref)
            succ_doc = try_parse_as_doc(docs, argname, label, value, chainspec, arg_ref)
            succ_co = try_parse_as_chain_opt(root_chain, argname, label, value, chainspec, arg_ref)
            succ_tf, curr_chain = try_parse_as_transform(curr_chain, argname, label, value, chainspec, arg_ref)
            succ_sum = (succ_ctx + succ_doc + succ_co + succ_tf)
            if succ_sum == 1:
                continue
            if succ_sum > 1:
                raise CliArgsParseException(arg_ref, f"ambiguous argument")
            raise CliArgsParseException(arg_ref, f"unknown argument")
    except scr_option.ScrOptionReassignmentError as ex:
        pass
    return (root_chain, docs, ctx_opts)
