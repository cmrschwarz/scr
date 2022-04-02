#!/usr/bin/env python3
import os
import json
import glob
import shellescape
import sys
import time
import subprocess
from enum import Enum
from multiprocessing import Pool, cpu_count

# cd into parent of scriptdir
os.chdir(os.path.dirname(os.path.abspath(os.path.realpath(__file__))) + "/..")
# prepend to path so we can call 'screp ...'
os.environ["PATH"] = "." + ":" + os.environ["PATH"]

ANSI_RED = "\033[0;31m"
ANSI_GREEN = "\033[0;32m"
ANSI_YELLOW = "\033[0;33m"
ANSI_CLEAR = "\033[0m"

DASH_BAR = "-" * 80


class TestOptions:
    tags_need: list[str] = []
    tags_avoid: list[str] = []
    parallelism: int = cpu_count()


def get_key_with_default(obj, key, default=""):
    return obj[key] if key in obj else default


def get_cmd_string(tc):
    cmd = tc.get("command", "screp")
    for arg in tc.get("args", []):
        cmd += " " + shellescape.quote(arg)
    return cmd


def timed_exec(func):
    start = time.monotonic_ns()
    res = func()
    end = time.monotonic_ns()
    elapsed_s = float(end - start) / 10**9
    if elapsed_s < 1:
        time_notice = f"{int(elapsed_s * 1000)} ms"
    else:
        time_notice = f"{elapsed_s:.2f} s"
    return res, time_notice


def execute_test(command, args, stdin):
    proc = subprocess.Popen(
        [command] + args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=os.environ
    )
    stdout, stderr = proc.communicate(input=stdin)
    return proc.returncode, stdout, stderr


def join_lines(lines):
    if not isinstance(lines, list):
        return lines
    return "\n".join(lines) + "\n"


class TestResult(Enum):
    SUCCESS = 0,
    FAILED = 1,
    SKIPPED = 2


def run_test(name, to: TestOptions):
    with open(name, "r") as f:
        try:
            tc = json.load(f)
        except json.JSONDecodeError as ex:
            print(f"{ANSI_RED}JSON PARSE ERROR in {name}: {str(ex)}{ANSI_CLEAR}")
            return TestResult.FAILED
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
        return TestResult.SKIPPED

    ec = tc.get("ec", 0)
    command = tc.get("command", "screp")
    args = tc.get("args", [])
    stdin = join_lines(tc.get("stdin", ""))
    expected_stdout = join_lines(tc.get("stdout", ""))
    expected_stderr = join_lines(tc.get("stderr", ""))
    if to.parallelism < 2:
        msg_inprogress = f"{ANSI_YELLOW}RUNNING {name}{ANSI_CLEAR}"
        sys.stdout.write(msg_inprogress)
        sys.stdout.flush()

    (exit_code, stdout, stderr), exec_time_str = timed_exec(
        lambda: execute_test(command, args, stdin))

    success = False
    if stderr != expected_stderr:
        reason = f"wrong stderr:\n{get_cmd_string(tc)}\n{stderr}{DASH_BAR}"
    elif stdout != expected_stdout:
        reason = f"wrong stdout:\n{get_cmd_string(tc)}\n{stdout}{DASH_BAR}"
    elif ec != exit_code:
        reason = f"wrong exitcode: {exit_code} (expected {ec})\n{get_cmd_string(tc)}"
    else:
        success = True
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
    return TestResult.SUCCESS if success else TestResult.FAILED


def run_test_wrapper(args):
    return run_test(*args)


def run_tests(to: TestOptions):
    results = {
        TestResult.SKIPPED: 0,
        TestResult.FAILED: 0,
        TestResult.SUCCESS: 0
    }
    tests = glob.glob("./test/cases/*.json")
    if to.parallelism < 2:
        for name in tests:
            res = run_test(name, to)
            results[res] += 1
        return results

    pool = Pool(to.parallelism)
    test_args = [(name, to) for name in tests]
    results_list = pool.map(run_test_wrapper, test_args)
    for res in results_list:
        results[res] += 1
    return results


def main():
    to = TestOptions()
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
        else:
            raise ValueError(f"unknown cli argument {arg}")
        i += 1

    if to.parallelism < 1:
        to.parallelism = 1

    results, exec_time_str = timed_exec(lambda: run_tests(to))

    if results[TestResult.SKIPPED]:
        skip_notice = f", {results[TestResult.SKIPPED]} test(s) skipped"
    else:
        skip_notice = ""

    if results[TestResult.FAILED]:
        print(
            f"{ANSI_RED}{results[TestResult.FAILED]} test(s) failed, {results[TestResult.SUCCESS]} test(s) passed{skip_notice}{ANSI_CLEAR} [{exec_time_str}]")
        return 1
    else:
        print(
            f"{ANSI_GREEN}{results[TestResult.SUCCESS]} test(s) passed{skip_notice}{ANSI_CLEAR} [{exec_time_str}]")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("")
        pass
