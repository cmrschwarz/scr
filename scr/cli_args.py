from scr import chain_options, context_options, document, chain_spec, scr_option, version, utils
from scr.transforms import transform, transform_catalog
from scr.selenium import selenium_options
from typing import Callable, Optional, Any
import re


class CliArgsParseException(Exception):
    arg_ref: tuple[int, str]

    def __init__(self, arg_ref: tuple[int, str], *args: Any) -> None:
        super().__init__(*args)
        self.arg_ref = arg_ref


def print_help() -> None:
    print(f"{version.SCR_NAME} [OPTIONS]")  # TODO


def try_parse_bool_arg_or_default(val: Optional[str], default: bool, arg_ref: tuple[int, str]) -> bool:
    if val is None:
        return default
    res = utils.try_parse_bool(val)
    if res is None:
        raise CliArgsParseException(arg_ref, "failed to parse as bool")
    return res


def try_parse_as_context_opt(
    ctx_opts: 'context_options.ContextOptions',
    argname: str,
    label: Optional[str],
    value: Optional[str],
    chainspec: Optional['chain_spec.ChainSpec'],
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
            raise CliArgsParseException(arg_ref, "cannot specify label for global argument")
        if chainspec is not None:
            raise CliArgsParseException(arg_ref, "cannot specify chain range for global argument")
    return matched


def try_parse_as_doc(
    root_chain: 'chain_options.ChainOptions',
    curr_chain: 'chain_options.ChainOptions',
    docs: list['document.Document'],
    argname: str,
    label: Optional[str],
    value: Optional[str],
    chainspec: Optional['chain_spec.ChainSpec'],
    arg_ref: tuple[int, str]
) -> bool:
    doc_source = document.DocumentSource.try_parse_type(argname)
    if doc_source is None:
        return False
    if label is not None:
        raise CliArgsParseException(arg_ref, "cannot specify label for document")
    if doc_source == document.DocumentSourceStdin:
        if value is not None:
            raise CliArgsParseException(arg_ref, "cannot specify value for stdin document")
    else:
        if value is None:
            if doc_source == document.DocumentSourceString:
                raise CliArgsParseException(arg_ref, "missing value for string document")
            raise CliArgsParseException(arg_ref, "missing source for document")
    cs = chainspec if chainspec is not None else chain_spec.ChainSpecCurrent()

    docs.append(document.Document(
        doc_source.from_str(value),
        document.DocumentReferencePointNone(),
        cs.rebase(curr_chain, root_chain))
    )
    return True


def try_parse_as_chain_opt(
    curr_chain: 'chain_options.ChainOptions',
    argname: str,
    label: Optional[str],
    value: Optional[str],
    chainspec: Optional['chain_spec.ChainSpec'],
    arg_ref: tuple[int, str]
) -> bool:
    def apply(fn: Callable[['chain_options.ChainOptions'], None]) -> None:
        if chainspec is None:
            fn(curr_chain)
        else:
            for co in chainspec.instantiate(curr_chain):
                fn(co)

    if "dte" == argname:
        if value is not None:
            v_ = value
            apply(lambda co: co.default_text_encoding.set(v_, arg_ref))
        else:
            raise CliArgsParseException(arg_ref, "missing argument for default text encoding")
    elif "ppte" == argname:
        ppte = try_parse_bool_arg_or_default(value, True, arg_ref)
        apply(lambda co: co.prefer_parent_text_encoding.set(ppte, arg_ref))
    elif "fte" == argname:
        fte = try_parse_bool_arg_or_default(value, True, arg_ref)
        apply(lambda co: co.force_text_encoding.set(fte, arg_ref))
    elif "selenium".startswith(argname):
        if value is None:
            sv = selenium_options.SeleniumVariant.DEFAULT
        else:
            sv_ = selenium_options.SeleniumVariant.try_parse(value)
            if sv_ is None:
                raise CliArgsParseException(arg_ref, "failed to parse selenium variant argument")
            sv = sv_
        apply(lambda co: co.selenium_variant.set(sv, arg_ref))
    elif "sds" == argname:
        if value is None:
            raise CliArgsParseException(arg_ref, "missing argument for selenium download strategy")
        else:
            sds_ = selenium_options.SeleniumDownloadStrategy.try_parse(value)
            if sds_ is None:
                raise CliArgsParseException(arg_ref, "failed to parse selenium download strategy")
            sds = sds_
        apply(lambda co: co.selenium_download_strategy.set(sds, arg_ref))
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


def parse(args: list[str]) -> tuple['chain_options.ChainOptions', list['document.Document'], 'context_options.ContextOptions']:
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
            succ_doc = try_parse_as_doc(root_chain, curr_chain, docs, argname, label, value, chainspec, arg_ref)
            succ_co = try_parse_as_chain_opt(root_chain, argname, label, value, chainspec, arg_ref)
            succ_tf, curr_chain = try_parse_as_transform(curr_chain, argname, label, value, chainspec, arg_ref)
            succ_sum = (succ_ctx + succ_doc + succ_co + succ_tf)
            if succ_sum == 1:
                continue
            if succ_sum > 1:
                raise CliArgsParseException(arg_ref, "ambiguous argument")
            raise CliArgsParseException(arg_ref, "unknown argument")
    except scr_option.ScrOptionReassignmentError as ex:
        arg_origin = ex.originating_cli_arg
        assert arg_origin is not None
        raise CliArgsParseException(arg_origin, *ex.args)
    return (root_chain, docs, ctx_opts)
