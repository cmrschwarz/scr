import os
from .cli_env import CliEnv, run_scr
from ...download_job import DEFAULT_RESPONSE_BUFFER_SIZE
import pytest
from os.path import normpath


def test_basic_xpath(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/foo+bar+baz.html",
            "cx= //ul/li/text()"
        ],
        stdout="foo\nbar\nbaz\n",
    )


def test_lic(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/foo+bar+baz.html",
            "cx=//ul/li/@id",
            "lic",
            "lx=../text()",
            "cpf={l}|{c}\n"
        ],
        stdout="foo|foo\nbar|bar\nbaz|baz\n",
    )


def test_filename_in_interactive_label(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/content_disposition.html",
            "cx=//iframe/@src",
            "lf={fn}",
            "cl",
            "lin",
            "cpf={l}\n",
            "csf=dummy.txt",  # so we get a proper filename
        ],
        stdin="y\n",
        output_files={"dummy.txt": None},
        stdout='"' + normpath("../res/content_disposition.html") + '": content link '
        + 'https://httpbin.org/response-headers?Access-Control-Expose-Headers='
        + 'Content-Disposition&Content-Disposition=attachment;filename=content_disposition'
        + ' (ci=1): accept content label "content_disposition" '
        + '[Yes/no/edit//chainskip/docskip]? content_disposition\n'
    )


def test_lic_with_text(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/foo+bar+baz.html",
            "cx=//ul/li/text()",
            "lic",
            "lx=../text()",
            "cpf={l}|{c}\n"
        ],
        stdout="foo|foo\nbar|bar\nbaz|baz\n",
    )


def test_cxs(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/foo+bar+baz.html",
            "cx=//ul/li[@id='bar']/text()",
            "cxs=1",
        ],
        stdout=["foo", "bar", "baz"]
    )


def test_cxs_deduplication(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/foo+bar+baz.html",
            "cx=//ul/li/text()",
            "cxs=1",
        ],
        stdout=["foo", "bar", "baz"]
    )


def test_cxs_no_dedup_on_unicode(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/two_lists.html",
            "cx=//*[@id='l1e1']/text()",
            "cxs=2",
        ],
        stdout=["foo", "bar", "baz", "foo", "bar", "baz"]
    )


def test_cxs_insufficient_level(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/two_lists.html",
            "cx=//*[@id='l1e1']/@id",
            "cxs=1",
        ],
        stdout=["l1e1", "l1e2", "l1e3"],
    )


def test_cm_available_in_cpf(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file0=../res/a.txt.html",
            "cx=//@src",
            "cl=1",
            "cpf={cm}\\n"
        ],
        stdout=f"{normpath('../res/a.txt')}\n",
    )


def test_connection_failed(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "url=xxx",
            "cr=.*"
        ],
        ec=1,
        stderr="[ERROR]: Failed to fetch https://xxx: connection failed\n",
    )


def test_broken_pipe(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            f"cmatch={'x' * (3 * DEFAULT_RESPONSE_BUFFER_SIZE)}",
            "cshif={c}",
            "cshf=python -c 'import time; time.sleep(1)'"
        ],
        ec=1,
        stderr="[ERROR]: broken pipe\n",
    )


def test_cfc(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file0=../res/foo+bar+baz.html",
            "cx0=//li/@id",
            "cfc0=1",
            "cpf0=match: {c}\n",
            "cr1=^(bar)$",
            "cpf1=fwd: {cg1}\n"
        ],
        stdout=["match: foo", "match: bar", "match: baz", "fwd: bar"],
    )


def test_data_url_download(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/data_url.html",
            "cx=//@src",
            "cl",
            "csf={fn}"
        ],
        output_files={"dl_001.dat": "data_url"}
    )


def test_data_urls(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/data_url.txt",
            "file=../res/data_url_base64.txt",
            "file=../res/data url with space.txt",
            "cr=^.+$",
            "cl=1"
        ],
        stdout=[
            "data_url",
            "data_url_base64",
            "data url with space"
        ],
    )


def test_disallow_empty_save_path(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/a.txt",
            "cr=.*",
            "csf="
        ],
        ec=1,
        stderr="[ERROR]: csf cannot be the empty string: csf=\n",
    )


def test_double_content_print_from_file(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/a.txt.html",
            "cl=1",
            "cx=//@src",
            "cpf={c}:::{c}"
        ],
        stdout="a\n:::a\n",
    )


def test_double_content_print_file_from_url(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/file_url.html",
            "cl=1",
            "cx=//@src",
            "cpf={c}:::{c}"
        ],
        stdout="file_url\n:::file_url\n",
    )


def test_document_deduplication(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/recursive_iframe.html",
            "file=../res/recursive_iframe_child.html",
            "dx=//iframe/@src",
            "cx=//title/text()",
            "dd=n"
        ],
        stdout=[
            "recursive_iframe", "recursive_iframe_child",
            "recursive_iframe_child", "recursive_iframe"
        ]
    )


def test_document_deduplication_unique(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/recursive_iframe.html",
            "file=../res/recursive_iframe_child.html",
            "dx=//iframe/@src",
            "cx=//title/text()",
        ],
        stdout=["recursive_iframe", "recursive_iframe_child"]
    )


def test_empty_cpf(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/a.txt",
            "cr=.*",
            "cpf="
        ],
        stdout="",
    )


def test_empty_document(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/empty.html",
            "cr=.*"
        ],
        stdout="\n",
    )


def test_download_file(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/a.txt.html",
            "cl=1",
            "cx=//@src",
            "csf0={fb}+{fb}{fe}",
            "cwf0={c}+\n{c}",
            "csf1=foo.txt"
        ],
        output_files={
            "a+a.txt": "a\n+\na\n",
            "foo.txt": "a\n"
        },
    )


@pytest.mark.httpbin()
def test_download_url(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/file_url.html",
            "cl=1",
            "cx=//@src",
            "lx=//@id",
            "csf0={fn}",
            "csf1={l}.txt"
        ],
        output_files={
            "file_url.txt": "file_url\n",
            "ZmlsZV91cmwK": "file_url\n"
        },
    )


def test_connection_timeout(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "url=http://httpbin.org/delay/5",
            "cpf={c}",
            "timeout=0.5"
        ],
        stderr=[
            "[ERROR]: Failed to fetch http://httpbin.org/delay/5: connection timeout"
        ],
        ec=1
    )


def test_filename_if_content_not_needed(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/data_url.html",
            "cx=//@src",
            "cl",
            "cpf={fn}\n"
        ],
        stdout=",data_url\n"
    )


def test_illegal_url(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "url=../res/basic.html",
            "cr=.",  # to not trigger doc as content optimization
            "cpf={c}"
        ],
        ec=1,
        stderr="[ERROR]: Failed to fetch https:///../res/basic.html: invalid url\n"
    )


def test_info_verbosity(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/iframe_tree.html",
            "v=info",
            "dx=//iframe/@src",
            "cx=//title/text()",
            "mt=0"
        ],
        stdout=[
            "iframe_tree",
            "iframe_tree_l",
            "iframe_tree_l1",
            "iframe_tree_l2",
            "iframe_tree_l3",
            "iframe_tree_r"
        ],
        stderr=[
            f" [INFO]: reading file '{normpath('../res/iframe_tree.html')}'",
            f" [INFO]: reading file '{normpath('../res/iframe_tree_l.html')}'",
            f" [INFO]: reading file '{normpath('../res/iframe_tree_l1.html')}'",
            f" [INFO]: reading file '{normpath('../res/iframe_tree_l2.html')}'",
            f" [INFO]: reading file '{normpath('../res/iframe_tree_l3.html')}'",
            f" [INFO]: reading file '{normpath('../res/iframe_tree_r.html')}'"
        ]
    )


def test_invalid_xpath(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/basic.html",
            "cx=??xxx"
        ],
        ec=1,
        stderr="[ERROR]: invalid xpath in cx=??xxx\n"
    )


def test_missing_argument(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "v"
        ],
        ec=1,
        stderr="[ERROR]: missing '=' and value for option 'v'\n"
    )


def test_multichain(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file0=../res/a.txt.html",
            "dx0=//@src",
            "doc0=1",
            "cx0=//@id",
            "cr1=a",
            "cpf1={cr}\n",
            "file2=../res/b.txt",
            "cr2=b",
            "cpf2={c}\n"
        ],
        stdout="a.txt\na\nb\n"
    )


def test_nonexisting_file(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/xxxxxxx",
            "cx=//p/text()"
        ],
        ec=1,
        stderr=f"[ERROR]: Failed to fetch {normpath('../res/xxxxxxx')}: no such file or directory\n"
    )


@pytest.mark.repl()
def test_cli_doc_reuse(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "repl",
            "rfile=../res/foo+bar+baz.html",
            "cx=//ul/li/text()"
        ],
        stdin=[
            "'cx=//ul/li/text()' cr=b.r",
            "exit"
        ],
        stdout="foo\nbar\nbaz\nbar\n"
    )


@pytest.mark.repl()
def test_repl_exit(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "repl"
        ],
        stdin="exit file=xxx cr=.",
        ec=1,
        stderr="[ERROR]: Failed to fetch xxx: no such file or directory\n"
    )


@pytest.mark.repl()
def test_repl_immediate_exit(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "repl",
            "exit"
        ],
    )


@pytest.mark.repl()
def test_tree_bfs(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/iframe_tree.html",
            "dx=//iframe/@src",
            "cpf={dl}\\n",
            "bfs=1"
        ],
        stdout=[
            f"{normpath('../res/iframe_tree.html')}",
            f"{normpath('../res/iframe_tree_l.html')}",
            f"{normpath('../res/iframe_tree_r.html')}",
            f"{normpath('../res/iframe_tree_l1.html')}",
            f"{normpath('../res/iframe_tree_l2.html')}",
            f"{normpath('../res/iframe_tree_l3.html')}"
        ]
    )


@pytest.mark.repl()
def test_tree_dfs(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/iframe_tree.html",
            "dx=//iframe/@src",
            "cpf={dl}\\n"
        ],
        stdout=[
            f"{normpath('../res/iframe_tree.html')}",
            f"{normpath('../res/iframe_tree_l.html')}",
            f"{normpath('../res/iframe_tree_l1.html')}",
            f"{normpath('../res/iframe_tree_l2.html')}",
            f"{normpath('../res/iframe_tree_l3.html')}",
            f"{normpath('../res/iframe_tree_r.html')}"
        ]
    )


def test_cshp(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/a.txt",
            "cshf=python -c 'import sys; sys.stdout.write(sys.stdin.read())'",
            "cshif={c}b\n",
            "cshp"
        ],
        stdout=f"a{os.linesep}b{os.linesep}"
    )


def test_cshp_single_threaded(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/a.txt",
            "cshf=python -c 'import sys; sys.stdout.write(sys.stdin.read())'",
            "cshif={c}b\n",
            "cshp",
            "mt=0"
        ],
        stdout=f"a{os.linesep}b{os.linesep}"
    )


def test_implicit_range_begin(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "cmatch=x",
            "cr-2=.+",
        ],
        stdout="x\nx\nx\n"
    )


def test_indoc_rfile(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "indoc=rfile",
            "cpf={c}"
        ],
        stdin="../res/a.txt",
        stdout="a\n"
    )


def test_indoc_implicit_cmatch(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "indoc",
            "cpf={c}"
        ],
        stdin="x",
        stdout="x"
    )
