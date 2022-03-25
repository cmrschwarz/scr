#!/usr/bin/env python3
import os
import textwrap
import json
import glob
import shellescape
import sys

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
    cmd = "screp"
    for arg in tc["args"]:
        cmd += " " + shellescape.quote(arg)
    return cmd

fails = 0
skipped = 0
successes = 0

tags_need = []
tags_avoid = []

for t in sys.argv[1:]:
    if not t: continue
    if t[0] == "-":
        tags_avoid.append(t[1:])
    else:
        tags_need.append(t)



for tf in glob.glob("./test/cases/*.json"):
    with open(tf, "r") as f:
        tc = json.load(f)
    name = tf
    tags = set(tc.get("tags", []))
    discard = False
    for t in tags_need:
        if t not in tags:
            discard = True
            break
    else:
        for t in tags_avoid:
            if t in tags:
                discard = True
                break
    if discard:
        skipped += 1
        # print(f"{ANSI_YELLOW}SKIPPED {name}{ANSI_CLEAR}")
        continue
    ec = tc.get("ec", 0)
    stdin = tc.get("stdin", "")
    expected_stdout = tc.get("stdout", "")
    expected_stderr = tc.get("stderr", "")
    msg_inprogress = f"{ANSI_YELLOW}RUNNING {name}{ANSI_CLEAR}"
    sys.stdout.write(msg_inprogress)
    sys.stdout.flush()
    proc = subprocess.Popen(
        ["screp"] + tc["args"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=os.environ
    )
    output = proc.communicate(input=stdin)
    success = False
    stdout = output[0]
    stderr = output[1]
    if stderr != expected_stderr:
        reason = f"wrong stderr:\n{get_cmd_string(tc)}\n{stderr}{DASH_BAR}"
    elif stdout != expected_stdout:
        reason = f"wrong stdout:\n{get_cmd_string(tc)}\n{stdout}{DASH_BAR}"
    elif ec != proc.returncode:
        reason = f"wrong exitcode: {proc.returncode} (expected {ec})\n{get_cmd_string(tc)}"
    else:
        success = True

    if success:
        msg_result = f"PASSED {name}"
        successes += 1
    else:
        nl = reason.find("\n")
        if nl == -1:
            reason += ANSI_CLEAR
        else:
            reason = reason[:nl] + ANSI_CLEAR + reason[nl:]

        msg_result = f"{ANSI_RED}FAILED {name}: {reason}"
        fails += 1
    if len(msg_result) < len(msg_inprogress):
        sys.stdout.write("\r" + " " * len(msg_inprogress))
    sys.stdout.write("\r" + msg_result + "\n")

if skipped:
    skip_notice = f", {skipped} test(s) skipped"
if fails:
    print(f"{ANSI_RED}{fails} test(s) failed, {successes} test(s) passed{skip_notice}{ANSI_CLEAR}")
else:
    print(
        f"{ANSI_GREEN}{successes} test(s) passed{skip_notice}{ANSI_CLEAR}")
