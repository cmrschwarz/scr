#!/usr/bin/env python3
import sys
import os
from ... import scr
import io
from typing import Any, Union
from enum import Enum
import json5
import glob
import pytest
import shellescape


ANSI_RED = "\033[0;31m"
ANSI_GREEN = "\033[0;32m"
ANSI_YELLOW = "\033[0;33m"
ANSI_CLEAR = "\033[0m"

DASH_BAR = "-" * 80


def get_cmd_string(args: list[str]) -> str:
    cmd: str = scr.SCRIPT_NAME
    for arg in args:
        cmd += " " + shellescape.quote(arg)
    return cmd


def join_lines(lines: Union[list[str], str]) -> str:
    if not isinstance(lines, list):
        return lines
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    "test_description_json_file",
    [
        os.path.relpath(f, os.path.dirname(__file__))
        for f in glob.glob(f"{os.path.dirname(__file__)}/cases/**/*.json")
    ]
)
def test_integration_json(
    test_description_json_file: str, tmpdir: Any,
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tmpdir = str(tmpdir)
    # we have one json file per test in /cases/** that describes input and expected
    # output (stout, err, exit code) for a scr command line invocation
    # this is for reusing legacy tests and slightly questionable,
    # but on the other hand allows us to copy paste failing test args into vscode launch.json
    with open(os.path.join(os.path.dirname(__file__), test_description_json_file), "r") as f:
        tc = json5.load(f)
    expected_exit_code = tc.get("ec", 0)
    args = tc.get("args", [])
    stdin = join_lines(tc.get("stdin", ""))
    expected_stdout = join_lines(tc.get("stdout", ""))
    expected_stderr = join_lines(tc.get("stderr", ""))
    output_files = tc.get("output_files", {})
    for ofn in output_files.keys():
        output_files[ofn] = join_lines(output_files[ofn])
    resource_dir = os.path.join(tmpdir, "res")
    os.symlink(
        os.path.join(os.path.dirname(__file__), "res"),
        resource_dir
    )
    os.chdir(tmpdir)

    if stdin:
        stdin_file_path = str(os.path.join(tmpdir, "_pytest_stdin"))
        stdin_mode = "w+"
    else:
        stdin_file_path = os.devnull
        stdin_mode = "r"

    with open(stdin_file_path, stdin_mode) as f_stdin:
        if stdin:
            f_stdin.write(stdin)
            f_stdin.seek(0)
        monkeypatch.setattr("sys.stdin", f_stdin)
        exit_code = scr.run_scr(["scr"] + args)

    cap = capsys.readouterr()
    stderr = cap.err
    stdout = cap.out
    success = False

    if stderr != expected_stderr:
        reason = f"wrong stderr:\n{stderr}{DASH_BAR}"
    elif stdout != expected_stdout:
        reason = f"wrong stdout:\n{stdout}{DASH_BAR}"
    elif expected_exit_code != exit_code:
        reason = f"wrong exitcode: {exit_code} (expected {expected_exit_code})"
    else:
        success = True

    if success and output_files:
        for fn, fv in output_files.items():
            fp = os.path.join(tmpdir, fn)
            try:
                with open(fp, "r") as f:
                    content = f.read()
                if content != fv:
                    reason = f"wrong output file content in {fn}:\n{fv}{DASH_BAR}"
                    success = False
                    break
            except FileNotFoundError:
                output_files = ", ".join(
                    [
                        os.path.relpath(f, tmpdir)
                        for f in glob.glob(str(tmpdir) + "/**")
                        if f != resource_dir
                    ]
                )
                reason = f"output file missing: '{fn}', present are: [{output_files}]"
                success = False
                break
    if not success:
        raise ValueError(
            f"{test_description_json_file}\n{test_description_json_file}\n{get_cmd_string(args)}\n{reason}")
