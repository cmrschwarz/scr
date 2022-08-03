from io import TextIOWrapper
import os
import tempfile
import pytest
from typing import Optional, cast, Generator, Union
from ... import scr
import re


class CliEnv():
    tmpdir: str
    capsys: pytest.CaptureFixture[str]
    monkeypatch: pytest.MonkeyPatch
    stdin_file: Optional[TextIOWrapper]
    special_files: set[str]

    def __init__(self, cli_env_dir: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
        self.tmpdir = tempfile.mkdtemp(dir=cli_env_dir)
        self.capsys = capsys
        self.monkeypatch = monkeypatch
        os.chdir(self.tmpdir)
        self.special_files = set()

    def set_stdin(self, stdin: str) -> None:
        if stdin:
            stdin_file_path = str(os.path.join(self.tmpdir, "_pytest_stdin"))
            stdin_mode = "w+"
            self.special_files.add("_pytest_stdin")
        else:
            stdin_file_path = os.devnull
            stdin_mode = "r"
        self.stdin_file = cast(
            TextIOWrapper, open(stdin_file_path, stdin_mode)
        )
        if stdin:
            self.stdin_file.write(stdin)
            self.stdin_file.seek(0)

    def close(self) -> None:
        if self.stdin_file is not None:
            self.stdin_file.close()


@pytest.fixture()
def cli_env(cli_env_root_dir: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> Generator[CliEnv, None, None]:
    cli_env = CliEnv(cli_env_root_dir, capsys, monkeypatch)
    yield cli_env
    cli_env.close()


def received_expected_strs(received: str, expected: str) -> str:
    return f"{'-' * 36}received{'-' * 36}\n{received}{'-' * 36}expected{'-' * 36}\n{expected}{'-' * 80}"


def join_lines(lines: Union[list[str], str]) -> str:
    if not isinstance(lines, list):
        return lines
    return "\n".join(lines) + "\n"


def run_scr(
    env: CliEnv,
    args: list[str],
    stdout: Union[list[str], str] = "",
    stderr: Union[list[str], str] = "",
    ec: int = 0,
    stdin: Union[list[str], str] = "",
    output_files: dict[str, str] = {},
    stdout_re: bool = False,
    stderr_re: bool = False
) -> None:
    stdin = join_lines(stdin)
    stdout = join_lines(stdout)
    stderr = join_lines(stderr)
    env.set_stdin(stdin)
    env.monkeypatch.setattr("sys.stdin", env.stdin_file)
    exit_code = scr.run_scr(["scr"] + args)
    cap = env.capsys.readouterr()
    if (
        (stderr_re and not re.match(stderr, cap.err, re.DOTALL))
        or
        (not stderr_re and stderr != cap.err)
    ):
        raise ValueError(
            f"wrong stderr:\n{received_expected_strs(cap.err, stderr)}"
        )
    if (
        (stdout_re and not re.match(stdout, cap.out, re.DOTALL))
        or
        (not stdout_re and stdout != cap.out)
    ):
        raise ValueError(
            f"wrong stdout:\n{received_expected_strs(cap.out, stdout)}"
        )
    if ec != exit_code:
        raise ValueError(
            f"wrong exit code: expected {ec}, received {exit_code}"
        )
    expected_files = sorted(output_files.keys())
    received_files = sorted({*os.listdir(env.tmpdir)} - env.special_files)
    if expected_files != received_files:
        res = received_expected_strs(
            "\n".join(received_files) + "\n" if received_files else "",
            "\n".join(expected_files) + "\n" if expected_files else ""
        )
        raise ValueError(
            f"incorrect file results:\n{res}"
        )
    for of in output_files.keys():
        with open(of) as f:
            received = f.read()
        expected = output_files[of]
        if expected is not None and received != expected:
            raise ValueError(
                f"output file '{of}' has wrong contents:\n{received_expected_strs(received, expected)}"
            )
