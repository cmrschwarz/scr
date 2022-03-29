#!/usr/bin/env python3
import os
import textwrap
import json
import glob
import shellescape
import sys
import time
import subprocess

# cd into parent of scriptdir
os.chdir(os.path.dirname(os.path.abspath(os.path.realpath(__file__))) + "/..")
# prepend to path so we can call 'screp ...'
os.environ["PATH"] = "." + ":" + os.environ["PATH"]

ANSI_RED = "\033[0;31m"
ANSI_GREEN = "\033[0;32m"
ANSI_YELLOW = "\033[0;33m"
ANSI_CLEAR = "\033[0m"

DASH_BAR = "-" * 80


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


def run_tests(tags_need, tags_avoid):
    fails = 0
    skipped = 0
    successes = 0
    for name in glob.glob("./test/cases/*.json"):
        with open(name, "r") as f:
            try:
                tc = json.load(f)
            except json.JSONDecodeError as ex:
                print(f"{ANSI_RED}JSON PARSE ERROR in {name}: {str(ex)}")
                continue
        tags = tc.get("tags", [])
        tags.append(name)
        discard = False
        for tn in tags_need:
            for t in tags:
                if tn in t:
                    break
            else:
                discard = True
                break
        else:
            for ta in tags_avoid:
                for t in tags:
                    if ta in t:
                        discard = True
                        break
        if discard:
            skipped += 1
            # print(f"{ANSI_YELLOW}SKIPPED {name}{ANSI_CLEAR}")
            continue

        ec = tc.get("ec", 0)
        command = tc.get("command", "screp")
        args = tc.get("args", [])
        stdin = tc.get("stdin", "")
        expected_stdout = tc.get("stdout", "")
        expected_stderr = tc.get("stderr", "")

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

        if success:
            msg_result = f"PASSED {name} [{exec_time_str}]"
            successes += 1
        else:
            nl = reason.find("\n")
            if nl == -1:
                reason += ANSI_CLEAR
            else:
                reason = reason[:nl] + ANSI_CLEAR + reason[nl:]

            msg_result = f"{ANSI_RED}FAILED {name} [{exec_time_str}]: {reason} "
            fails += 1
        if len(msg_result) < len(msg_inprogress):
            sys.stdout.write("\r" + " " * len(msg_inprogress))
        sys.stdout.write("\r" + msg_result + "\n")
    return successes, fails, skipped


def main():
    tags_need = []
    tags_avoid = []

    for t in sys.argv[1:]:
        if not t:
            continue
        if t[0] == "-":
            tags_avoid.append(t[1:])
        else:
            tags_need.append(t)

    (successes, fails, skipped), exec_time_str = timed_exec(
        lambda: run_tests(tags_need, tags_avoid))

    if skipped:
        skip_notice = f", {skipped} test(s) skipped"
    else:
        skip_notice = ""

    if fails:
        print(
            f"{ANSI_RED}{fails} test(s) failed, {successes} test(s) passed{skip_notice}{ANSI_CLEAR} [{exec_time_str}]")
        return 1
    else:
        print(
            f"{ANSI_GREEN}{successes} test(s) passed{skip_notice}{ANSI_CLEAR} [{exec_time_str}]")
        return 0


if __name__ == "__main__":
    sys.exit(main())
