from .cli_env import CliEnv, run_scr_raw
from ..utils import validate_text
from ...download_job import DEFAULT_RESPONSE_BUFFER_SIZE
from ...progress_report import DEFAULT_MAX_TERMINAL_LINE_LENGTH


def test_broken_pipe_status_report(cli_env: CliEnv) -> None:
    res = run_scr_raw(
        cli_env,
        args=[
            f"str={'x' * (3 * DEFAULT_RESPONSE_BUFFER_SIZE)}",
            "cshif={c}",
            "cshf=python -c 'import time; time.sleep(0.1)'",
            "prog"
        ],
    )
    res.validate_file_results({})
    res.validate_exit_code(1)
    res.validate_stderr("")
    lines = res.stdout.splitlines()

    last_line = "\x1b\\[1F[0-9\\.:]+ [s,m]  \\[     !! broken pipe !!      \\]   ---   python -c 'import time; time.sleep\\(0.1\\)' *"
    validate_text("incorrect last line of status report", last_line, lines[-1], True)


def test_filesize_report(cli_env: CliEnv, _fake_time: None) -> None:
    res = run_scr_raw(
        cli_env,
        args=[
            "rstr=https://httpbin.org/bytes/1024",
            "csf=out.dat",
            "cl",
            "prog"
        ],
    )
    res.validate_file_results({"out.dat": None})
    res.validate_exit_code(0)
    res.validate_stderr("")
    lines = res.stdout.splitlines()
    last_line = '\x1b[1F0.0 s  ??? B/s [==============================] 1.00 KiB / 1.00 KiB  ---      out.dat'
    last_line += " " * (DEFAULT_MAX_TERMINAL_LINE_LENGTH - len(last_line) + len("\x1b[1F"))
    validate_text("incorrect last line of status report", last_line, lines[-1])


def test_speed_report(cli_env: CliEnv) -> None:
    res = run_scr_raw(
        cli_env,
        args=[
            "rstr=https://httpbin.org/bytes/1024",
            "csf=out.dat",
            "cl",
            "prog"
        ],
    )
    res.validate_file_results({"out.dat": None})
    res.validate_exit_code(0)
    res.validate_stderr("")
    lines = res.stdout.splitlines()
    last_line = "\x1b\\[1F[0-9\\.:]+ [s,m]  [0-9\\.]+ [GMKiB]+/s \\[==============================\\] 1\\.00 KiB / 1\\.00 KiB  ---      out.dat *"
    validate_text("incorrect last line of status report", last_line, lines[-1], True)
