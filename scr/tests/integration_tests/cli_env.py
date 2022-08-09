from io import TextIOWrapper
import os
import tempfile
import pytest
from typing import Optional, cast, Generator, Union
from ... import scr
from ..utils import USE_PYTEST_ASSERTIONS, received_expected_strs, validate_text, join_lines


class CliEnv():
    tmpdir: str
    capfd: pytest.CaptureFixture[str]
    monkeypatch: pytest.MonkeyPatch
    stdin_file: Optional[TextIOWrapper]
    special_files: set[str]

    def __init__(self, cli_env_dir: str, capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
        self.tmpdir = tempfile.mkdtemp(dir=cli_env_dir)
        self.capfd = capfd
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
def cli_env(cli_env_root_dir: str, capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> Generator[CliEnv, None, None]:
    cli_env = CliEnv(cli_env_root_dir, capfd, monkeypatch)
    yield cli_env
    cli_env.close()


class ScrRunResults:
    exit_code: int
    stdout: str
    stderr: str
    received_files: dict[str, str]

    def __init__(self) -> None:
        self.received_files = {}

    def validate_exit_code(self, expected: int) -> None:
        if expected != self.exit_code:
            if USE_PYTEST_ASSERTIONS:
                assert expected == self.exit_code, "wrong exit code"
            else:
                raise ValueError(
                    f"wrong exit code: expected {expected}, received {self.exit_code}"
                )

    def validate_stdout(self, expected: str, regex: bool = False) -> None:
        validate_text("wrong stdout", expected, self.stdout, regex)

    def validate_stderr(self, expected: str, regex: bool = False) -> None:
        validate_text("wrong stderr", expected, self.stderr, regex)

    def validate_file_results(self, expected_files: dict[str, Optional[str]]) -> None:
        expected_file_names = sorted(expected_files.keys())
        received_file_names = sorted(self.received_files.keys())
        if expected_file_names != received_file_names:
            if USE_PYTEST_ASSERTIONS:
                assert expected_file_names == received_file_names, "wrong files created"
            else:
                rec_ex_strs = received_expected_strs(
                    "\n".join(expected_file_names) + "\n" if expected_file_names else "",
                    "\n".join(received_file_names) + "\n" if received_file_names else ""
                )
                raise ValueError(
                    f"incorrect file results:\n{rec_ex_strs}"
                )
        for of in expected_files.keys():
            with open(of) as f:
                received = f.read()
            expected = expected_files[of]
            if expected is not None:
                validate_text(f"output file '{of}' has wrong contents", expected, received, False)


def run_scr_raw(
    env: CliEnv,
    args: list[str],
    stdin: Union[list[str], str] = ""
) -> ScrRunResults:
    stdin = join_lines(stdin)
    env.set_stdin(stdin)
    env.monkeypatch.setattr("sys.stdin", env.stdin_file)
    exit_code = scr.run_scr(["scr"] + args)
    cap = env.capfd.readouterr()
    res = ScrRunResults()
    res.stdout = cap.out
    res.stderr = cap.err
    res.exit_code = exit_code
    received_files = sorted({*os.listdir(env.tmpdir)} - env.special_files)
    for rf in received_files:
        with open(rf) as f:
            res.received_files[rf] = f.read()
    return res


def run_scr(
    env: CliEnv,
    args: list[str],
    stdout: Union[list[str], str] = "",
    stderr: Union[list[str], str] = "",
    ec: int = 0,
    stdin: Union[list[str], str] = "",
    output_files: dict[str, Optional[str]] = {},
    stdout_re: bool = False,
    stderr_re: bool = False
) -> None:
    stdout = join_lines(stdout)
    stderr = join_lines(stderr)
    res = run_scr_raw(env, args, stdin)
    res.validate_stderr(stderr, stderr_re)
    res.validate_stdout(stdout, stdout_re)
    res.validate_file_results(output_files)
    res.validate_exit_code(ec)
