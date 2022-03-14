#!/usr/bin/env python3
import os
import textwrap
import json
import glob
import sys

import subprocess

# cd into parent of scriptdir
os.chdir(os.path.dirname(os.path.abspath(os.path.realpath(__file__))) + "/..")
# prepend to path so we can call 'screp ...'
sys.path = [os.getcwd()] + sys.path

ANSI_RED = "\033[0;31m"
ANSI_GREEN = "\033[0;32m"
ANSI_CLEAR = "\033[0m"

DASH_BAR = "-" * 80


def get_key_with_default(obj, key, default=""):
    return obj[key] if key in obj else default


fails = 0
successes = 0

for tf in glob.glob("./test/cases/*.json"):
    with open(tf, "r") as f:
        tc = json.load(f)
    name = tf
    ec = tc.get("ec", 0)
    args = tc["args"]
    stdin = tc.get("stdin", "")
    expected_stdout = tc.get("stdout", "")
    expected_stderr = tc.get("stderr", "")

    proc = subprocess.Popen(
        ["bash", "-c", "screp " + args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8"
    )
    output = proc.communicate(input=stdin)
    success = False
    stdout = output[0]
    stderr = output[1]
    if stderr != expected_stderr:
        print(
            f"{ANSI_RED}FAILED {name}:{ANSI_CLEAR} wrong stderr:\n{stderr}{DASH_BAR}")
    elif stdout != expected_stdout:
        print(
            f"{ANSI_RED}FAILED {name}:{ANSI_CLEAR} wrong stdout:\n{stdout}{DASH_BAR}")
    elif ec != proc.returncode:
        print(
            f"{ANSI_RED}FAILED {name}:{ANSI_CLEAR} wrong exitcode: {proc.returncode} (expected {ec})")
    else:
        print(
            f"{ANSI_GREEN}PASSED {name}{ANSI_CLEAR}")
        success = True
    if success:
        successes += 1
    else:
        fails += 1


if fails:
    print(f"{ANSI_RED}{fails} test(s) failed, {successes} test(s) passed{ANSI_CLEAR}")
else:
    print(
        f"{ANSI_GREEN}{fails} test(s) failed, {successes} test(s) passed{ANSI_CLEAR}")
