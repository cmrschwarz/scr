from .cli_env import CliEnv, run_scr
import pytest
from os.path import normpath


@pytest.mark.selenium()
def test_closing_doc(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/closing_doc.html",
            "cx=//p/text()",
            "sel=f",
            "selh"
        ],
        ec=1,
        stderr="[ERROR]: the selenium instance was closed unexpectedly\n",
    )


@pytest.mark.selenium()
@pytest.mark.cmrs_io()
def test_cors(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/cors.html",
            "cx=//embed/@src",
            "sel=c",
            "cl=t",
            "cpf={c}",
            "seldl0=e",
            "seldl1=f",
            "selh"
        ],
        ec=1,
        stdout="cors\n",
        stderr=f"[ERROR]: {normpath('../res/cors.html')} (ci=1): selenium download of 'http://echo.d.cmrs.io/?echo=cors' failed (potential CORS issue): Failed to fetch\n",
    )


@pytest.mark.selenium()
def test_dedup(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/foo+bar+foo.html",
            "cx= //ul/li/text()",
            "sel=f",
            "selstrat=dedup",
            "selh"
        ],
        stdin="y\n",
        stdout=[
            f"{normpath('../res/foo+bar+foo.html')}: use page with potentially   < 2 >   contents [Yes/skip]? foo",
            "bar"
        ]
    )


@pytest.mark.selenium()
def test_js_content(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "rfile=../res/js_content.html",
            "cx=//p/text()",
            "sel=c",
            "selh"
        ],
        stdout=[
            "js_content"
        ]
    )


@pytest.mark.selenium()
def test_js_exec_causes_reload(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "sel=f",
            "file=../res/a.txt.html",
            "cx0=//@id",
            "cr0=[^\\.]+$",
            "cjs0=const a = document.createElement('a');a.id=cr; a.text = cx; document.body.appendChild(a); return 'hello from js';",
            "cx1=//a[@id='txt']/text()",
            "selh"
        ],
        stdout=[
            "hello from js",
            "a.txt"
        ]
    )


@pytest.mark.selenium()
def test_recursive_iframes(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/iframe_tree.html",
            "cx=//title/text()",
            "sel=c",
            "selh"
        ],
        stdout=[
            "iframe_tree",
            "iframe_tree_l",
            "iframe_tree_l1",
            "iframe_tree_l2",
            "iframe_tree_l3",
            "iframe_tree_r"
        ]
    )


@pytest.mark.selenium()
def test_recursive_shadow_roots(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/shadow_root.html", "cx=//div", "sel", "selh"
        ],
        stdout=[
            '<div id="a">a<div id="b">b<div id="c">c<div id="a">d</div></div></div></div>',
            '<div id="b">b<div id="c">c<div id="a">d</div></div></div>',
            '<div id="c">c<div id="a">d</div></div>',
            '<div id="a">d</div>'
        ]
    )


@pytest.mark.selenium()
@pytest.mark.repl()
def test_repl_selenium(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "repl",
            "selh",
            "sel=d"
        ],
        stdin=[
            "file=../res/a.txt cpf={c}",
            "file=../res/js_content.html",
            "'cx=//p/text()'",
            "sel=f",
            "'cx=//p/text()'",
            # firefox is weird and wraps this
            "file=../res/b.txt cpf={c} cx=//pre/text()",
            "file=../res/js_content.html",
            "'cx=//p/text()'",
            "sel=d",
            "'cx=//p/text()'",
            "file=../res/a.txt cpf={c}",
            "cpf='c\\n'",
            "exit"
        ],
        stdout=[
            "a",
            "js_content",
            "b",
            "js_content",
            "a",
            "c"
        ]
    )


@pytest.mark.selenium()
@pytest.mark.httpbin()
def test_selenium_download_chrome(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/a.txt.html",
            "rfile=../res/file_url.html",
            "cl=1",
            "cx=//@src",
            "cpf={c}",
            "seldl0=e",
            "seldl1=f",
            "seldl2=i",
            "sel=c",
            "selh"
        ],
        ec=1,
        stdout=[
            "a",
            "a",
            "a",
            "file_url",
            "file_url",
        ],
        stderr="[ERROR]: http://httpbin.org/base64/ZmlsZV91cmwK (ci=1): failed to download: seldl=internal does not work across origins\n"
    )


@pytest.mark.selenium()
@pytest.mark.httpbin()
def test_selenium_download_firefox(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "file=../res/a.txt.html",
            "rfile=../res/file_url.html",
            "cl=1",
            "cx=//@src",
            "cpf={c}",
            "seldl0=e",
            "seldl1=f",
            "seldl2=i",
            "sel=f",
            "selh"
        ],
        ec=1,
        stdout=[
            "a",
            "a",
            "a",
            "file_url",
            "file_url",
        ],
        stderr="[ERROR]: http://httpbin.org/base64/ZmlsZV91cmwK (ci=1): failed to download: seldl=internal does not work across origins\n"
    )


@pytest.mark.selenium()
def test_selenium_install_firefox(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "selinstall=f"
        ],
        ec=0,
        stderr="(.* \\[INFO\\]: Firefox driver installed| \\[INFO\\]: existing Firefox driver found)\n",
        stderr_re=True
    )


@pytest.mark.selenium()
def test_selenium_embed_expansion(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=["file=../res/a.txt.html", "cx=//embed//body//text()", "sel=f", "selh"],
        stdout="a\n\n"
    )


@pytest.mark.selenium()
def test_selenium_object_expansion(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=["file=../res/a.txt_object.html", "cx=//object//body//text()", "sel=f", "selh"],
        stdout="a\n\n"
    )


@pytest.mark.selenium()
def test_selenium_js_fail(cli_env: CliEnv) -> None:
    run_scr(
        cli_env,
        args=[
            "sel=f",
            "selh",
            "file=../res/empty.html",
            "cjs=xxx"
        ],
        ec=0,
        stderr=[
            r' \[WARN\]: cjs: js exception on '
            + (
                normpath("../res/empty.html")
                .replace("\\", "\\\\")
                .replace(".", "\\.")
            )
            + ':.*'
        ],
        stderr_re=True
    )
