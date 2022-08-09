from .cli_env import CliEnv, run_scr_raw
from ..utils import validate_text
from ...download_job import DEFAULT_RESPONSE_BUFFER_SIZE
from ...progress_report import DEFAULT_MAX_TERMINAL_LINE_LENGTH


def test_broken_pipe_status_report(cli_env: CliEnv) -> None:
    res = run_scr_raw(
        cli_env,
        args=[
            f"cmatch={'x' * (3 * DEFAULT_RESPONSE_BUFFER_SIZE)}",
            "cshif={c}",
            "cshf=python -c 'import time; time.sleep(0.1)'",
            "prog"
        ],
    )
    res.validate_file_results({})
    res.validate_exit_code(1)
    res.validate_stderr("")
    lines = res.stdout.splitlines()
    first_line = '0.0 s  [***                           ]   <shell command>'
    first_line += " " * (DEFAULT_MAX_TERMINAL_LINE_LENGTH - len(first_line))
    validate_text("incorrect first line of status report", first_line, lines[0])

    last_line = "\x1b\\[1F[0-9\\.:]+ [s,m]  \\[     !! broken pipe !!      \\]   ---   python -c 'import time; time.sleep\\(0.1\\)' *"
    validate_text("incorrect last line of status report", last_line, lines[-1], True)