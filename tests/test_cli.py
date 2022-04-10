#!/usr/bin/env python3
from multiprocessing import Pool, cpu_count
from typing import Any, Union, TypeVar, Callable, Optional, cast
from enum import Enum
import os
import json5
import glob
import shellescape
import sys
import time
import subprocess
import shutil
import tempfile
import scr

ANSI_RED = "\033[0;31m"
ANSI_GREEN = "\033[0;32m"
ANSI_YELLOW = "\033[0;33m"
ANSI_CLEAR = "\033[0m"

DASH_BAR = "-" * 80

T = TypeVar('T')


class TOptions:  # can't name this TestOptions because of pytest...
    tags_need: list[str]
    tags_avoid: list[str]
    parallelism: int = cpu_count()
    scr_main_dir: str
    script_dir: str
    script_dir_abs: str
    script_dir_name: str
    test_output_dir: str
    test_dummy_dir: str
    fail_early: bool = False

    def __init__(self) -> None:
        self.tags_need = []
        self.tags_avoid = []


class TResult(Enum):
    SUCCESS = 0,
    FAILED = 1,
    SKIPPED = 2


def get_cmd_string(tc: dict[str, Any]) -> str:
    cmd: str = tc.get("command", "scr.py")
    args: list[str] = tc.get("args", [])
    assert type(args) is list
    for arg in args:
        cmd += " " + shellescape.quote(arg)
    return cmd


def timed_exec(func: Callable[[], T]) -> tuple[T, str]:
    start = time.monotonic_ns()
    res = func()
    end = time.monotonic_ns()
    elapsed_s = float(end - start) / 10**9
    if elapsed_s < 1:
        time_notice = f"{int(elapsed_s * 1000)} ms"
    else:
        time_notice = f"{elapsed_s:.2f} s"
    return res, time_notice


def execute_test(command: str, args: list[str], stdin: str, cwd: str) -> tuple[int, str, str]:
    proc = subprocess.Popen(
        [command] + args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=os.environ,
        cwd=cwd
    )
    stdout, stderr = proc.communicate(input=stdin)
    return proc.returncode, stdout, stderr


def join_lines(lines: Union[list[str], str]) -> str:
    if not isinstance(lines, list):
        return lines
    return "\n".join(lines) + "\n"


def run_test(name: str, to: TOptions) -> TResult:
    with open(name, "r") as f:
        try:
            tc = json5.load(f)
        except ValueError as ex:
            print(f"{ANSI_RED}JSON PARSE ERROR in {name}: {str(ex)}{ANSI_CLEAR}")
            return TResult.FAILED
    tags = tc.get("tags", [])
    tags.append(name)
    discard = False
    for tn in to.tags_need:
        for t in tags:
            if tn in t:
                break
        else:
            discard = True
            break
    else:
        for ta in to.tags_avoid:
            for t in tags:
                if ta in t:
                    discard = True
                    break
    if discard:
        # print(f"{ANSI_YELLOW}SKIPPED {name}{ANSI_CLEAR}")
        return TResult.SKIPPED

    ec = tc.get("ec", 0)
    command = tc.get("command", "scr.py")
    args = tc.get("args", [])
    stdin = join_lines(tc.get("stdin", ""))
    expected_stdout = join_lines(tc.get("stdout", ""))
    expected_stderr = join_lines(tc.get("stderr", ""))
    output_files = tc.get("output_files", {})
    for ofn in output_files.keys():
        output_files[ofn] = join_lines(output_files[ofn])
    if output_files:
        cwd = os.path.join(to.test_output_dir, f"{xhash(name)}")
        os.mkdir(cwd)
    else:
        cwd = to.test_dummy_dir

    if to.parallelism < 2:
        msg_inprogress = f"{ANSI_YELLOW}RUNNING {name}{ANSI_CLEAR}"
        sys.stdout.write(msg_inprogress)
        sys.stdout.flush()

    (exit_code, stdout, stderr), exec_time_str = timed_exec(
        lambda: execute_test(command, args, stdin, cwd)
    )

    success = False
    if stderr != expected_stderr:
        reason = f"wrong stderr:\n{get_cmd_string(tc)}\n{stderr}{DASH_BAR}"
    elif stdout != expected_stdout:
        reason = f"wrong stdout:\n{get_cmd_string(tc)}\n{stdout}{DASH_BAR}"
    elif ec != exit_code:
        reason = f"wrong exitcode: {exit_code} (expected {ec})\n{get_cmd_string(tc)}"
    else:
        success = True

    if success and output_files:
        for fn, fv in output_files.items():
            fp = os.path.join(cwd, fn)
            try:
                with open(fp, "r") as f:
                    content = f.read()
                if content != fv:
                    reason = f"wrong output file content in {fn}:\n{get_cmd_string(tc)}\n{fv}{DASH_BAR}"
                    success = False
                    break
            except FileNotFoundError:
                output_files = ", ".join(
                    [
                        os.path.relpath(f, cwd)
                        for f in glob.glob(cwd + "/**")
                        if f != os.path.join(cwd, to.script_dir_name)
                    ]
                )
                reason = f"output file missing: '{fn}', present are: [{output_files}]\n{get_cmd_string(tc)}"
                success = False
                break
    msg = ""
    if success:
        msg = f"PASSED {name} [{exec_time_str}]"
    else:
        nl = reason.find("\n")
        if nl == -1:
            reason += ANSI_CLEAR
        else:
            reason = reason[:nl] + ANSI_CLEAR + reason[nl:]

        msg = f"{ANSI_RED}FAILED {name} [{exec_time_str}]: {reason} "

    if to.parallelism < 2:
        if len(msg) < len(msg_inprogress):
            msg = "\r" + " " * len(msg) + "\r" + msg
        else:
            msg = "\r" + msg
    msg += "\n"
    sys.stdout.write(msg)
    return TResult.SUCCESS if success else TResult.FAILED


def run_test_wrapper(args: tuple[str, TOptions]) -> TResult:
    return run_test(*args)


def run_tests(to: TOptions) -> dict[TResult, int]:
    results = {
        TResult.SKIPPED: 0,
        TResult.FAILED: 0,
        TResult.SUCCESS: 0
    }

    tests = glob.glob(f"{to.script_dir}/cases/**/*.json", recursive=True)
    if to.parallelism < 2:
        for name in tests:
            res = run_test(name, to)
            results[res] += 1
            if to.fail_early and res == TResult.FAILED:
                break
        return results

    pool = Pool(to.parallelism)
    test_args = [(name, to) for name in tests]

    results_list = pool.map(run_test_wrapper, test_args)
    for res in results_list:
        results[res] += 1
    return results


def xhash(input: Any = None) -> str:
    if input is None:
        input = time.time_ns()
    return hex(hash(input))[3:]


# can't be named test_run because of pytest...
def test_cli() -> int:
    to = TOptions()
    to.script_dir_abs = os.path.dirname(
        os.path.abspath(os.path.realpath(__file__))
    )
    to.script_dir = os.path.relpath(to.script_dir_abs)
    to.script_dir_name = os.path.basename(to.script_dir)

    # cd into parent of scriptdir
    os.chdir(os.path.join(to.script_dir_abs, ".."))

    to.scr_main_dir = os.path.abspath(
        os.path.realpath(os.path.dirname(scr.__file__))
    )

    # create temp dir for test output
    to.test_output_dir = tempfile.mkdtemp(prefix="scr_test_")

    # so ../tests/res/... links still work with the changed cwd
    os.symlink(
        to.script_dir_abs,
        os.path.join(to.test_output_dir, to.script_dir_name),
        True
    )

    # dummy dir for tests that don't create files
    to.test_dummy_dir = os.path.join(to.test_output_dir, "dummy")
    os.mkdir(to.test_dummy_dir)

    try:
        # prepend the scr folder to the PATH so the tests can use it
        os.environ["PATH"] = (to.scr_main_dir + ":" + os.environ["PATH"])
        i = 1
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == "-x":
                to.tags_avoid.extend(sys.argv[i+1].split(","))
                i += 1
            elif arg == "-o":
                to.tags_need.extend(sys.argv[i+1].split(","))
                i += 1
            elif arg == "-s":
                to.parallelism = 1
            elif arg == "-j":
                to.parallelism = int(sys.argv[i+1])
                i += 1
            elif arg == "-f":
                to.fail_early = True
                to.parallelism = 1
            else:
                raise ValueError(f"unknown cli argument {arg}")
            i += 1

        if to.parallelism < 1:
            to.parallelism = 1

        results, exec_time_str = timed_exec(lambda: run_tests(to))
    finally:
        shutil.rmtree(to.test_output_dir)

    if results[TResult.SKIPPED]:
        skip_notice = f", {results[TResult.SKIPPED]} test(s) skipped"
    else:
        skip_notice = ""

    if results[TResult.FAILED]:
        msg = f"{ANSI_RED}{results[TResult.FAILED]} test(s) failed, {results[TResult.SUCCESS]} test(s) passed{skip_notice}{ANSI_CLEAR} [{exec_time_str}]"
        print(msg)
        # so pytest can report this
        raise ValueError(msg)
    else:
        print(
            f"{ANSI_GREEN}{results[TResult.SUCCESS]} test(s) passed{skip_notice}{ANSI_CLEAR} [{exec_time_str}]")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(test_cli())
    except ValueError as ae:
        exit(1)
    except KeyboardInterrupt:
        print("")
        pass