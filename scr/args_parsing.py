from typing import Any, Optional, Callable, Iterable
import itertools
import copy
from .definitions import (
    T, ScrSetupError, DocumentType, SeleniumVariant, selenium_variants_dict,
    selenium_strats_dict, selenium_download_strategies_dict, verbosities_dict,
    document_duplication_dict,
    VERSION, SCRIPT_NAME, DEFAULT_ESCAPE_SEQUENCE, DEFAULT_CPF, DEFAULT_CWF,
    DEFAULT_TIMEOUT_SECONDS
)

from . import (
    match_chain, document, input_sequences,
    selenium_driver_download, scr_context
)
import sys
import re

MATCH_CHAIN_ARGUMENT_REGEX = re.compile("^[0-9\\-\\*\\^]*$")


def help(err: bool = False) -> None:
    text = f"""{SCRIPT_NAME} [OPTIONS]

    Matching chains are evaluated in the following order, skipping unspecified steps:
    xpath -> regex -> (javascript) -> python format string

    Content to Write out:
        cx=<xpath>            xpath for content matching
        cr=<regex>            regex for content matching
        cjs=<js string>       javascript to execute on the page, format args are available as js variables (selenium only)
        cf=<format string>    content format string (args: <cr capture groups>, xmatch, rmatch, di, ci)
        cxs=<int|empty>       also match siblings of xpath match in parents up to this number of levels (empty means any, default: 0)
        cmm=<bool>            allow multiple content matches in one document instead of picking the first (defaults to true)
        cimin=<int>           initial content index, each successful match gets one index
        cimax=<int>           max content index, matching stops here
        cicont=<bool>         don't reset the content index for each document
        csf=<format string>   save content to file at the path resulting from the format string, empty to enable
        cwf=<format string>   format to write to file. defaults to \"{DEFAULT_CWF}\"
        cpf=<format string>   print the result of this format string for each content, empty to disable
                              defaults to \"{DEFAULT_CPF}\" if cpf, csf and cfc are unspecified
        cshf=<format string>  execute a shell command resulting from the given format string
        cshif=<format string> format for the stdin of cshf
        cshp=<bool>           print the output of the shell commands on stdout and stderr
        cfc=<chain spec>      forward content match as a virtual document
        cff=<format string>   format of the virtual document forwarded to the cfc chains. defaults to \"{DEFAULT_CWF}\"
        csin=<bool>           give a prompt to edit the save path for a file
        cin=<bool>            give a prompt to ignore a potential content match
        cl=<bool>             treat content match as a link to the actual content
        cesc=<string>         escape sequence to terminate content in cin mode, defaults to \"{DEFAULT_ESCAPE_SEQUENCE}\"

    Labels to give each matched content (mostly useful for the filename in csf):
        lx=<xpath>           xpath for label matching
        lr=<regex>           regex for label matching
        ljs=<js string>      javascript to execute on the page, format args are available as js variables (selenium only)
        lf=<format string>   label format string
        lxs=<int|empty>      also match siblings of xpath match in parents up to this number of levels (empty means any, default: 0)
        lic=<bool>           match for the label within the content match instead of the hole document
        las=<bool>           allow slashes in labels
        lmm=<bool>           allow multiple label matches in one document instead of picking the first (for all content matches)
        lam=<bool>           allow missing label (default is to skip content if no label is found)
        lfd=<format string>  default label format string to use if there's no match
        lin=<bool>           give a prompt to edit the generated label

    Further documents to scan referenced in already found ones:
        dx=<xpath>           xpath for document matching
        dr=<regex>           regex for document matching
        djs=<js string>      javascript to execute on the page, format args are available as js variables (selenium only)
        df=<format string>   document format string
        dxs=<int|empty>      also match siblings of xpath match in parents up to this number of levels (empty means any, default: 0)
        dimin=<int>          initial document index, each successful match gets one index
        dimax=<int>          max document index, matching stops here
        dmm=<bool>           allow multiple document matches in one document instead of picking the first
        din=<bool>           give a prompt to ignore a potential document match
        denc=<encoding>      default document encoding to use for following documents, default is utf-8
        dfenc=<bool>         force document encoding for following documents, even if http(s) says differently
        dsch=<scheme>        default scheme for urls derived from following documents, defaults to "https"
        dpsch=<bool>         use the parent documents scheme if available, defaults to true unless dsch is specified
        dfsch=<bool>         force the default scheme for urls derived from following documents
        doc=<chain spec>     chains that matched documents should apply to, default is the same chain
        dd=<duplication>     whether to allow document duplication (default: unique, values: allowed, nonrecursive, unique)
        rbase=<url>         default base for relative urls from rfile, rstring and rstdin documents
        base=<path>         default base for relative file pathes from string and stdin documents, default: current working directory
        fbase=bool          force the default d(r)base even if the originating document has a valid base

    Initial Documents (may be specified multiple times):
        url=<url>            fetch document from url
        rfile=<path>         read document from path
        file=<path>          read document from path, urls without scheme are treated as relative file pathes
        rstr=<string>        treat string as document
        str=<string>         treat string as document, urls without scheme are treated as relative file pathes
        rstdin               read document from stdin
        stdin                read document from stdin, urls without scheme are treated as relative file pathes

    Other:
        selstrat=<strategy>  matching strategy for selenium (default: plain, values: anymatch, plain, interactive, deduplicate)
        seldl=<dl strategy>  download strategy for selenium (default: external, values: external, internal, fetch)
        owf=<bool>           allow to overwrite existing files, defaults to true

    Format Args:
        Named arguments for <format string> arguments.
        Some only become available later in the pipeline (e.g. {{cm}} is not available inside cf).

        {{cx}}                 content xpath match
        {{cr}}                 content regex match, equal to {{cx}} if cr is unspecified
        <cr capture groups>  the named regex capture groups (?P<name>...) from cr are available as {{name}},
                             the unnamed ones (...) as {{cg<unnamed capture group number>}}
        {{cf}}                 content after applying cf
        {{cjs}}                output of cjs
        {{cm}}                 final content match after link normalization (cl) and user interaction (cin)
        {{c}}                  content, downloaded from cm in case of cl, otherwise equal to cm

        {{lx}}                 label xpath match
        {{lr}}                 label regex match, equal to {{lx}} if lr is unspecified
        <lr capture groups>  the named regex capture groups (?P<name>...) from cr are available as {{name}},
                             the unnamed ones (...) as {{lg<unnamed capture group number>}}
        {{lf}}                 label after applying lf
        {{ljs}}                output of ljs
        {{l}}                  final label after user interaction (lin)

        {{dx}}                 document link xpath match
        {{dr}}                 document link regex match, equal to {{dx}} if dr is unspecified
        <dr capture groups>  the named regex capture groups (?P<name>...) from dr are available as {{name}},
                             the unnamed ones (...) as {{dg<unnamed capture group number>}}
        {{df}}                 document link after applying df
        {{djs}}                output of djs
        {{d}}                  final document link after user interaction (din)

        {{di}}                 document index
        {{ci}}                 content index
        {{dl}}                 document link (inside df, this refers to the parent document)
        {{denc}}               content encoding, deduced while respecting denc and dfenc
        {{cesc}}               escape sequence for separating content, can be overwritten using cesc
        {{chain}}              id of the match chain that generated this content

        {{fn}}                 filename from the url of a cm with cl
        {{fb}}                 basename component of {{fn}} (extension stripped away)
        {{fe}}                 extension component of {{fn}}, including the dot (empty string if there is no extension)


    Chain Syntax:
        Any option above can restrict the matching chains is should apply to using opt<chainspec>=<value>.
        Use "-" for ranges, "," for multiple specifications, and "^" to except the following chains.
        Examples:
            lf1,3-5=foo        sets "lf" to "foo" for chains 1, 3, 4 and 5.
            lf2-^4=bar         sets "lf" to "bar" for all chains larger than or equal to 2, except chain 4

    Miscellaneous:
        help                   prints this help
        selinstall=<browser>   installs selenium driver for the specified browser in the directory of this script
        seluninstall=<browser> uninstalls selenium driver for the specified browser in the directory of this script
        selupdate=<browser>    updates (or installs) the local selenium driver for the specified browser
        version                print version information

    Global Options:
        timeout=<float>        seconds before a web request timeouts (default {DEFAULT_TIMEOUT_SECONDS})
        bfs=<bool>             traverse the matched documents in breadth first order instead of depth first
        v=<verbosity>          output verbosity levels (default: warn, values: info, warn, error)
        prog=<bool>            whether to display progress bars for content downloads (defaults to true if stdout is a tty)
        ua=<string>            user agent to pass in the html header for url GETs
        uar=<bool>             use a rangom user agent
        selkeep=<bool>         keep selenium instance alive after the command finished
        cookiefile=<path>      path to a netscape cookie file. cookies are passed along for url GETs
        sel=<browser|empty>    use selenium to load urls into an interactive browser session
                               (empty means firefox, default: disabled, values: tor, chrome, firefox, disabled)
        selh=<bool>            use selenium in headless mode, implies sel
        tbdir=<path>           root directory of the tor browser installation, implies sel=tor
                               (default: environment variable TOR_BROWSER_DIR)
        mt=<int>               maximum threads for background downloads, 0 to disable. defaults to cpu core count
        repl=<bool>            accept commands in a read eval print loop
        exit=<bool>            exit the repl (with the result of the current command)

        """.strip()
    if err:
        log_raw(text + "\n")
        sys.exit(1)

    else:
        print(text)


def parse_mc_range_int(ctx: 'scr_context.ScrContext', v: str, arg: str) -> int:
    try:
        return int(v)
    except ValueError:
        raise ScrSetupError(
            f"failed to parse '{v}' as an integer for match chain specification of '{arg}'"
        )


def extend_match_chain_list(ctx: 'scr_context.ScrContext', needed_id: int) -> None:
    if len(ctx.match_chains) > needed_id:
        return
    for i in range(len(ctx.match_chains), needed_id+1):
        mc = copy.deepcopy(ctx.origin_mc)
        mc.chain_id = i
        ctx.match_chains.append(mc)


def parse_simple_mc_range(ctx: 'scr_context.ScrContext', mc_spec: str, arg: str) -> Iterable['match_chain.MatchChain']:
    sections = mc_spec.split(",")
    ranges = []
    for s in sections:
        s = s.strip()
        if s == "":
            raise ScrSetupError(
                "invalid empty range in match chain specification of '{arg}'")
        dash_split = [r.strip() for r in s.split("-")]
        if len(dash_split) > 2 or s == "-":
            raise ScrSetupError(
                f"invalid range '{s}' in match chain specification of '{arg}'")
        if len(dash_split) == 1:
            id = parse_mc_range_int(ctx, dash_split[0], arg)
            extend_match_chain_list(ctx, id)
            ranges.append([ctx.match_chains[id]])
        else:
            lhs, rhs = dash_split
            if lhs == "":
                fst = 0
            else:
                fst = parse_mc_range_int(ctx, lhs, arg)
            if rhs == "":
                extend_match_chain_list(ctx, fst)
                snd = len(ctx.match_chains) - 1
                ranges.append([ctx.origin_mc])
            else:
                snd = parse_mc_range_int(ctx, dash_split[1], arg)
                if fst > snd:
                    raise ScrSetupError(
                        f"second value must be larger than first for range {s} "
                        + f"in match chain specification of '{arg}'"
                    )
                extend_match_chain_list(ctx, snd)
            ranges.append(ctx.match_chains[fst: snd + 1])
    return itertools.chain(*ranges)


def match_traditional_cli_arg(arg: str, true_opt_name: str, aliases: set[str]) -> Optional[bool]:
    tolen = len(true_opt_name)
    arglen = len(arg)
    if arg.startswith(f"{true_opt_name}"):
        if arglen > tolen:
            if arg[tolen] != "=":
                return None
        return parse_bool_arg(arg[len("{true_opt_name}="):], arg)
    if arg in aliases:
        return True
    return None


def parse_mc_range(ctx: 'scr_context.ScrContext', mc_spec: str, arg: str) -> Iterable['match_chain.MatchChain']:
    if mc_spec == "":
        return [ctx.defaults_mc]

    esc_split = [x.strip() for x in mc_spec.split("^")]
    if len(esc_split) > 2:
        raise ScrSetupError(
            f"cannot have more than one '^' in match chain specification of '{arg}'"
        )
    if len(esc_split) == 1:
        return parse_simple_mc_range(ctx, mc_spec, arg)
    lhs, rhs = esc_split
    if lhs == "":
        exclude = parse_simple_mc_range(ctx, rhs, arg)
        include: Iterable[match_chain.MatchChain] = itertools.chain(
            ctx.match_chains, [ctx.origin_mc])
    else:
        exclude = parse_simple_mc_range(ctx, rhs, arg)
        chain_count = len(ctx.match_chains)
        include = parse_simple_mc_range(ctx, lhs, arg)
        # hack: parse exclude again so the newly generated chains form include are respected
        if chain_count != len(ctx.match_chains):
            exclude = parse_simple_mc_range(ctx, rhs, arg)
    return ({*include} - {*exclude})


def parse_mc_arg(
    ctx: 'scr_context.ScrContext', argname: str, arg: str,
    support_blank: bool = False
) -> Optional[tuple[Iterable['match_chain.MatchChain'], Optional[str]]]:
    if not arg.startswith(argname):
        return None
    argname_len = len(argname)
    eq_pos = arg.find("=")
    if eq_pos == -1:
        mc_spec = arg[argname_len:]
        if arg != argname:
            if not MATCH_CHAIN_ARGUMENT_REGEX.match(mc_spec):
                return None
        elif not support_blank:
            raise ScrSetupError(f"missing equals sign in argument '{arg}'")
        pre_eq_arg = arg
        value = None
    else:
        mc_spec = arg[argname_len: eq_pos]
        if not MATCH_CHAIN_ARGUMENT_REGEX.match(mc_spec):
            return None
        pre_eq_arg = arg[:eq_pos]
        value = arg[eq_pos+1:]
    return parse_mc_range(ctx, mc_spec, pre_eq_arg), value


def parse_mc_arg_as_range(
    ctx: 'scr_context.ScrContext', argname: str, argval: str
) -> list['match_chain.MatchChain']:
    return list(parse_mc_range(ctx, argval, argname))


def apply_mc_arg(
    ctx: 'scr_context.ScrContext', argname: str, config_opt_names: list[str], arg: str,
    value_parse: Callable[[str, str], Any] = lambda x, _arg: x,
    support_blank: bool = False, blank_value: Optional[Any] = None
) -> bool:
    parse_result = parse_mc_arg(ctx, argname, arg, support_blank)
    if parse_result is None:
        return False
    mcs, value = parse_result
    if value is None:
        if blank_value is None:
            value = value_parse("", arg)
        else:
            value = blank_value
    else:
        value = value_parse(value, arg)
    mcs = list(mcs)
    # so the lowest possible chain generates potential errors
    mcs.sort(key=lambda mc: mc.chain_id if mc.chain_id else float("inf"))
    for mc in mcs:
        prev = mc.try_set_config_option(config_opt_names, value, arg)
        if prev is not None:
            if mc is ctx.origin_mc:
                chainid = str(max(len(ctx.match_chains), 1))
            elif mc is ctx.defaults_mc:
                chainid = ""
            else:
                chainid = str(mc.chain_id)
            raise ScrSetupError(
                f"{argname}{chainid} specified twice in: "
                + f"'{prev}' and '{arg}'"
            )

    return True


def get_arg_val(arg: str) -> str:
    return arg[arg.find("=") + 1:]


def parse_bool_arg(v: str, arg: str, blank_val: bool = True) -> bool:
    v = v.strip().lower()
    if v == "" and blank_val is not None:
        return blank_val

    if v in input_sequences.YES_INDICATING_STRINGS.matching:
        return True
    if v in input_sequences.NO_INDICATING_STRINGS.matching:
        return False
    raise ScrSetupError(f"cannot parse '{v}' as a boolean in '{arg}'")


def parse_int_arg(v: str, arg: str) -> int:
    try:
        return int(v)
    except ValueError:
        raise ScrSetupError(f"cannot parse '{v}' as an integer in '{arg}'")


def parse_non_negative_int_arg(v: str, arg: str) -> int:
    i = parse_int_arg(v, arg)
    if i < 0:
        raise ScrSetupError(f"illegal negative value '{v}' for '{arg}'")
    return i


def parse_non_negative_float_arg(v: str, arg: str) -> float:
    try:
        f = float(v)
    except ValueError:
        raise ScrSetupError(f"cannot parse '{v}' as an number in '{arg}'")
    if f < 0:
        raise ScrSetupError(f"negative number '{v}' not allowed for '{arg}'")
    return f


def parse_encoding_arg(v: str, arg: str) -> str:
    if not verify_encoding(v):
        raise ScrSetupError(f"unknown encoding in '{arg}'")
    return v


def select_variant(val: str, variants_dict: dict[str, T], default: Optional[T] = None) -> Optional[T]:
    val = val.strip().lower()
    if val == "":
        return default
    if val in variants_dict:
        return variants_dict[val]
    match = None
    for k, v in variants_dict.items():
        if k.startswith(val):
            if match is not None:
                return None  # we have two conflicting matches
            match = v
    return match


def parse_variant_arg(val: str, variants_dict: dict[str, T], arg: str, default: Optional[T] = None) -> T:
    res = select_variant(val, variants_dict, default)
    if res is None:
        raise ScrSetupError(
            f"illegal argument '{arg}', valid options for "
            + f"{arg[:len(arg)-len(val)-1]} are: "
            + f"{', '.join(sorted(variants_dict.keys()))}"
        )
    return res


def verify_encoding(encoding: str) -> bool:
    try:
        "!".encode(encoding=encoding)
        return True
    except UnicodeEncodeError:
        return False


def gen_doc_from_arg(
    ctx: 'scr_context.ScrContext',
    mcs: list['match_chain.MatchChain'], extend_chains_above: Optional[int],
    doctype: DocumentType, value: str
) -> 'document.Document':
    if doctype.non_r_type() == DocumentType.STRING:
        path = None
    else:
        path = value
    doc = document.Document(
        doctype,
        path=path,
        src_mc=None,
        parent_doc=None,
        match_chains=mcs,
        expand_match_chains_above=extend_chains_above,
    )
    if doctype.non_r_type() == DocumentType.STRING:
        doc.text = value
    return doc


def parse_doc_arg(
    ctx: 'scr_context.ScrContext', argname: str, arg: str, supports_blank: bool
) -> Optional[tuple[list['match_chain.MatchChain'], Optional[int], Optional[str]]]:
    parse_result = parse_mc_arg(ctx, argname, arg, supports_blank)
    if parse_result is None:
        return None
    mcs, value = parse_result
    mcs = list(mcs)
    if mcs == [ctx.defaults_mc]:
        extend_chains_above = len(ctx.match_chains)
        mcs = list(ctx.match_chains)
    elif ctx.origin_mc in mcs:
        mcs.remove(ctx.origin_mc)
        extend_chains_above = len(ctx.match_chains)
    else:
        extend_chains_above = None
    return (mcs, extend_chains_above, value)


def apply_doc_arg(
    ctx: 'scr_context.ScrContext', argname: str, doctype: 'DocumentType', arg: str
) -> bool:
    parse_result = parse_doc_arg(ctx, argname, arg, False)
    if parse_result is None:
        return False
    mcs, extend_chains_above, value = parse_result
    assert value is not None
    ctx.docs.append(gen_doc_from_arg(ctx, mcs, extend_chains_above, doctype, value))
    return True


def apply_doc_arg_stdin(ctx: 'scr_context.ScrContext', argname: str, arg: str, doctype: DocumentType) -> bool:
    parse_result = parse_doc_arg(ctx, argname, arg, True)
    if parse_result is None:
        return False
    mcs, extend_chains_above, value = parse_result
    if value is not None:
        raise ScrSetupError(
            f"{argname} does not take an argument: '{arg}'"
        )
    if ctx.stdin_text is None:
        ctx.stdin_text = sys.stdin.read()
    ctx.docs.append(gen_doc_from_arg(ctx, mcs, extend_chains_above, doctype, ctx.stdin_text))
    return True


def parse_plain_arg(
    optname: str, arg: str,
    value_parse: Callable[[str, str], Any] = lambda x, _arg: x,
    support_blank: bool = False,
    blank_val: Optional[Any] = None
) -> Optional[Any]:
    if not arg.startswith(optname):
        return None
    if len(optname) == len(arg):
        if support_blank:
            if blank_val is None:
                val = value_parse("", arg)
            else:
                val = blank_val
        else:
            raise ScrSetupError(
                f"missing '=' and value for option '{optname}'"
            )
    else:
        nc = arg[len(optname):]
        if MATCH_CHAIN_ARGUMENT_REGEX.match(nc):
            raise ScrSetupError(
                "option '{optname}' does not support match chain specification"
            )
        if nc[0] != "=":
            return None
        val = value_parse(get_arg_val(arg), arg)
    return val


def apply_ctx_arg(
    ctx: 'scr_context.ScrContext', optname: str, argname: str, arg: str,
    value_parse: Callable[[str, str], Any] = lambda x, _arg: x,
    support_blank: bool = False,
    blank_val: Any = None
) -> bool:
    val = parse_plain_arg(optname, arg, value_parse, support_blank, blank_val)
    if val is None:
        return False
    if ctx.has_custom_value([argname]):
        raise ScrSetupError(f"error: {argname} specified twice")
    ctx.try_set_config_option([argname], val, arg)
    return True


def parse_selenium_variants(value: str, arg: str) -> Optional['SeleniumVariant']:
    return parse_variant_arg(value, selenium_variants_dict, arg)


def print_version() -> None:
    print(f"{SCRIPT_NAME} {VERSION}")


def parse_args(ctx: 'scr_context.ScrContext', args: Iterable[str]) -> None:
    for arg in args:
        if match_traditional_cli_arg(arg, "help", {"-h", "--help"}):
            help()
            ctx.special_args_occured = True
            continue
        if match_traditional_cli_arg(arg, "version", {"-v", "--version"}):
            print_version()
            ctx.special_args_occured = True
            continue

        driver_install = parse_plain_arg(
            "selinstall", arg, parse_selenium_variants
        )
        if driver_install is not None:
            selenium_driver_download.install_selenium_driver(
                ctx, driver_install, False
            )
            ctx.special_args_occured = True
            continue

        driver_update = parse_plain_arg(
            "selupdate", arg, parse_selenium_variants
        )
        if driver_update is not None:
            selenium_driver_download.install_selenium_driver(
                ctx, driver_update, True
            )
            ctx.special_args_occured = True
            continue

        driver_uninstall = parse_plain_arg(
            "seluninstall", arg, parse_selenium_variants
        )
        if driver_uninstall is not None:
            selenium_driver_download.uninstall_selenium_driver(
                ctx, driver_uninstall
            )
            ctx.special_args_occured = True
            continue

        # we need a "infinite" int value default fox cxs/lxs/dxs
        int_max = 2**64 - 1

        # content args
        if apply_mc_arg(ctx, "cx", ["loc_content", "xpath"], arg):
            continue
        if apply_mc_arg(ctx, "cr", ["loc_content", "regex"], arg):
            continue
        if apply_mc_arg(ctx, "cf", ["loc_content", "format"], arg):
            continue
        if apply_mc_arg(ctx, "cjs", ["loc_content", "js_script"], arg):
            continue
        if apply_mc_arg(ctx, "cxs", ["loc_content", "xpath_sibling_match_depth"], arg, parse_non_negative_int_arg, True, int_max):
            continue
        if apply_mc_arg(ctx, "cmm", ["loc_content", "multimatch"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "cin", ["loc_content", "interactive"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "cimin", ["cimin"], arg, parse_int_arg):
            continue
        if apply_mc_arg(ctx, "cimax", ["cimax"], arg, parse_int_arg):
            continue
        if apply_mc_arg(ctx, "cicont", ["ci_continuous"], arg, parse_bool_arg, True):
            continue

        if apply_mc_arg(ctx, "cff", ["content_forward_format"], arg):
            continue
        if apply_mc_arg(ctx, "cfc", ["content_forward_chains"], arg, lambda v, arg: parse_mc_arg_as_range(ctx, arg, v)):
            continue
        if apply_mc_arg(ctx, "cpf", ["content_print_format"], arg):
            continue
        if apply_mc_arg(ctx, "cwf", ["content_write_format"], arg):
            continue
        if apply_mc_arg(ctx, "csf", ["content_save_format"], arg):
            continue
        if apply_mc_arg(ctx, "cshf", ["content_shell_command_format"], arg):
            continue
        if apply_mc_arg(ctx, "cshif", ["content_shell_command_stdin_format"], arg):
            continue
        if apply_mc_arg(ctx, "cshp", ["content_shell_command_print_output"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "csin", ["save_path_interactive"], arg, parse_bool_arg, True):
            continue

        if apply_mc_arg(ctx, "cienc", ["content_input_encoding"], arg, parse_encoding_arg):
            continue
        if apply_mc_arg(ctx, "cfienc", ["content_force_input_encoding"], arg, parse_encoding_arg):
            continue

        if apply_mc_arg(ctx, "cl", ["content_raw"], arg, lambda v, arg: not parse_bool_arg(v, arg), True): continue
        if apply_mc_arg(ctx, "cesc", ["content_escape_sequence"], arg):
            continue

        # label args
        if apply_mc_arg(ctx, "lx", ["loc_label", "xpath"], arg):
            continue
        if apply_mc_arg(ctx, "lr", ["loc_label", "regex"], arg):
            continue
        if apply_mc_arg(ctx, "lf", ["loc_label", "format"], arg):
            continue
        if apply_mc_arg(ctx, "ljs", ["loc_label", "js_script"], arg):
            continue
        if apply_mc_arg(ctx, "lxs", ["loc_label", "xpath_sibling_match_depth"], arg, parse_non_negative_int_arg, True, int_max):
            continue
        if apply_mc_arg(ctx, "lmm", ["loc_label", "multimatch"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "lin", ["loc_label", "interactive"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "las", ["allow_slashes_in_labels"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "lic", ["labels_inside_content"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "lam", ["label_allow_missing"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "ldf", ["label_default_format"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "fdf", ["filename_default_format"], arg, parse_bool_arg, True):
            continue

        # document args
        if apply_mc_arg(ctx, "dx", ["loc_document", "xpath"], arg):
            continue
        if apply_mc_arg(ctx, "dr", ["loc_document", "regex"], arg):
            continue
        if apply_mc_arg(ctx, "df", ["loc_document", "format"], arg):
            continue
        if apply_mc_arg(ctx, "djs", ["loc_document", "js_script"], arg):
            continue
        if apply_mc_arg(ctx, "dxs", ["loc_document", "xpath_sibling_match_depth"], arg, parse_non_negative_int_arg, True, int_max):
            continue
        if apply_mc_arg(ctx, "doc", ["document_output_chains"], arg, lambda v, arg: parse_mc_arg_as_range(ctx, arg, v)):
            continue
        if apply_mc_arg(ctx, "dmm", ["loc_document", "multimatch"], arg, parse_bool_arg, True):
            continue
        if apply_mc_arg(ctx, "din", ["loc_document", "interactive"], arg, parse_bool_arg, True):
            continue

        if apply_mc_arg(ctx, "dimin", ["dimin"], arg, parse_int_arg):
            continue
        if apply_mc_arg(ctx, "dimax", ["dimax"], arg, parse_int_arg):
            continue

        if apply_mc_arg(ctx, "owf", ["overwrite_files"], arg, parse_bool_arg, True):
            continue

        if apply_mc_arg(ctx, "denc", ["default_document_encoding"], arg, parse_encoding_arg):
            continue
        if apply_mc_arg(ctx, "dfenc", ["force_document_encoding"], arg, parse_encoding_arg):
            continue

        if apply_mc_arg(ctx, "dsch", ["default_document_scheme"], arg):
            continue
        if apply_mc_arg(ctx, "dpsch", ["prefer_parent_document_scheme"], arg):
            continue
        if apply_mc_arg(ctx, "dfsch", ["force_document_scheme"], arg, parse_bool_arg, True):
            continue

        if apply_mc_arg(
            ctx, "dd", ["document_duplication"], arg,
            lambda v, arg: parse_variant_arg(v, document_duplication_dict, arg),
        ): continue

        if apply_mc_arg(ctx, "base", ["file_base"], arg):
            continue

        if apply_mc_arg(ctx, "rbase", ["url_base"], arg):
            continue

        if apply_mc_arg(ctx, "fbase", ["force_mc_base"], arg, parse_bool_arg, True):
            continue

        # misc args
        if apply_mc_arg(
            ctx, "selstrat", ["selenium_strategy"], arg,
            lambda v, arg: parse_variant_arg(v, selenium_strats_dict, arg)
        ): continue
        if apply_mc_arg(
            ctx, "seldl", ["selenium_download_strategy"], arg,
            lambda v, arg: parse_variant_arg(v, selenium_download_strategies_dict, arg)
        ): continue

        # Documents
        if apply_doc_arg(ctx, "url", DocumentType.URL, arg):
            continue
        if apply_doc_arg(ctx, "rfile", DocumentType.RFILE, arg):
            continue
        if apply_doc_arg(ctx, "file", DocumentType.FILE, arg):
            continue
        if apply_doc_arg(ctx, "str", DocumentType.STRING, arg):
            continue
        if apply_doc_arg(ctx, "rstr", DocumentType.RSTRING, arg):
            continue
        if apply_doc_arg_stdin(ctx, "stdin", arg, DocumentType.STRING):
            continue
        if apply_doc_arg_stdin(ctx, "rstdin", arg, DocumentType.RSTRING):
            continue

        if apply_ctx_arg(ctx, "cookiefile", "cookie_file", arg):
            continue

        # Global Options
        if apply_ctx_arg(
            ctx, "sel", "selenium_variant", arg,
            lambda v, arg: parse_variant_arg(
                v, selenium_variants_dict, arg, SeleniumVariant.FIREFOX
            ),
            True
        ): continue
        if apply_ctx_arg(ctx, "selh", "selenium_headless", arg, parse_bool_arg, True):
            continue
        if apply_ctx_arg(ctx, "selkeep", "selenium_keep_alive", arg, parse_bool_arg, True):
            continue
        if apply_ctx_arg(ctx, "tbdir", "tor_browser_dir", arg):
            continue
        if apply_ctx_arg(ctx, "bfs", "documents_bfs", arg, parse_bool_arg, True):
            continue
        if apply_ctx_arg(ctx, "ua", "user_agent", arg):
            continue
        if apply_ctx_arg(ctx, "uar", "user_agent_random", arg, parse_bool_arg, True):
            continue
        if apply_ctx_arg(ctx, "v", "verbosity", arg, lambda v, arg: parse_variant_arg(v, verbosities_dict, arg)):
            continue
        if apply_ctx_arg(ctx, "prog", "enable_status_reports", arg, parse_bool_arg, True):
            continue

        if apply_ctx_arg(ctx, "repl", "repl", arg,  parse_bool_arg, True):
            continue

        if apply_ctx_arg(ctx, "mt", "max_download_threads", arg,  parse_int_arg):
            continue

        if apply_ctx_arg(ctx, "--repl", "repl", arg,  parse_bool_arg, True):
            continue

        if apply_ctx_arg(ctx, "exit", "exit", arg,  parse_bool_arg, True):
            continue

        if apply_ctx_arg(ctx, "timeout", "request_timeout_seconds", arg,  parse_non_negative_float_arg):
            continue

        raise ScrSetupError(f"unrecognized option: '{arg}'")
