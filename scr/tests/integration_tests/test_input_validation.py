from .cli_env import CliEnv, run_scr
import pytest


def test_allow_chain_on_bool_param(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/a.txt.html",
            "cx=//@src",
            "cl0"
        ],
        stdout="a\n\n",
    )


def test_backslash_excape_fail_unicode(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "cpf=\\"
        ],
        ec=1,
        stderr="[ERROR]: unterminated escape sequence '\\' in cpf=\\\n",
    )


def test_backslash_excape_fail(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "cpf=\\uf"
        ],
        ec=1,
        stderr="[ERROR]: invalid escape code \\uf in cpf=\\uf\n",
    )


def test_content_unavailable_in_csf(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "csf0-2={c}"
        ],
        ec=1,
        stderr="[ERROR]: unavailable key '{c}' in csf0-2={c}\n",
    )


def test_disallow_option_reassignment_doc(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "doc=1-4",
            "doc=1"
        ],
        ec=1,
        stderr="[ERROR]: doc specified twice in: 'doc=1-4' and 'doc=1'\n",
    )


def test_disallow_option_reassignment(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "cx3=//foo",
            "cx1-=//bar"
        ],
        ec=1,
        stderr="[ERROR]: cx3 specified twice in: 'cx3=//foo' and 'cx1-=//bar'\n",
    )


def test_disallow_unused_match_chain_first(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "url3=xxx"
        ],
        ec=1,
        stderr="[ERROR]: match chain 0 is unused, it has neither document nor content matching\n"
    )


def test_disallow_unused_match_chain_multichain(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "url=xxx"
        ],
        ec=1,
        stderr="[ERROR]: match chain 0 is unused, it has neither document nor content matching\n"
    )


def test_disallow_unused_match_chain(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "url0=xxx",
            "cr1=.*"
        ],
        ec=1,
        stderr="[ERROR]: match chain 0 is unused, it has neither document nor content matching\n"
    )


def test_label_format_unavailable_in_label_format(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=xxx",
            "cpf={c}",
            "lf={lm}"
        ],
        ec=1,
        stderr="[ERROR]: unavailable key '{lm}' in lf={lm}\n"
    )


def test_no_cx_if_only_regex_match(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "cr=.",
            "cpf={cx}"
        ],
        ec=1,
        stderr="[ERROR]: unavailable key '{cx}' in cpf={cx}\n"
    )


def test_no_url_error(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "cr=.",
        ],
        ec=1,
        stderr="[ERROR]: must specify at least one url or (r)file\n"
    )


def test_invalid_range(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "cr1-0=.",
        ],
        ec=1,
        stderr="[ERROR]: second value must be larger than first for range 1-0 in match chain specification of 'cr1-0'\n"
    )


@pytest.mark.repl()
def test_no_url_error_repl(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "repl"
        ],
        stdin="exit cr=.",
        ec=1,
        stderr="[ERROR]: must specify at least one url or (r)file\n"
    )


@pytest.mark.repl()
def test_repl_invalid_xpath(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "repl"
        ],
        stdin=[
            "rfile=./tes../res/basic.html",
            "cx0-2=//foo@bar",
            "exit"
        ],
        ec=0,
        stderr="[ERROR]: invalid xpath in cx0-2=//foo@bar\n"
    )


def test_unknown_format_key_in_write(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "lr=.",
            "csf={l}",
            "cwf={xxx}"
        ],
        ec=1,
        stderr="[ERROR]: unavailable key '{xxx}' in cwf={xxx}\n"
    )


def test_unknown_format_key(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "cpf={xxx}"
        ],
        ec=1,
        stderr="[ERROR]: unavailable key '{xxx}' in cpf={xxx}\n"
    )


def test_unknown_param_explicit_chain(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/empty.html",
            "cxx12=3"
        ],
        ec=1,
        stderr="[ERROR]: unrecognized option: 'cxx12=3'\n"
    )


def test_unknown_param(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/empty.html",
            "cxx=3"
        ],
        ec=1,
        stderr="[ERROR]: unrecognized option: 'cxx=3'\n"
    )


def test_unknown_variant(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "v="
        ],
        ec=1,
        stderr="[ERROR]: illegal argument 'v=', valid options for v are: debug, error, info, warn\n"
    )
