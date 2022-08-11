from .. import progress_report, download_job
from typing import cast
import pytest
import datetime
from collections import deque
from .conftest import FAKE_TIME_ORIGIN


@pytest.mark.parametrize(('byte_size', 'output_size', 'output_unit'), [
    (1000, "1000", " B"),
    (-1, "-1", " B"),
    (0, "0", " B"),
    (1024, "1.00", " KiB"),
    (2**91, "2048.00", " YiB")
])
def test_get_byte_size_string_ints(byte_size: int, output_size: str, output_unit: str) -> None:
    assert (
        progress_report.get_byte_size_string(byte_size)
        ==
        (output_size, output_unit)
    )


@pytest.mark.parametrize(('timespan', 'output_size', 'output_unit'), [
    (0, "0.0", " s"),
    (-1, "-1.0", " s"),
    (60, "01:00", " m"),
    (59.99, "01:00", " m"),
    (59.49, "59.5", " s")
])
def test_get_timespan_string(timespan: float, output_size: str, output_unit: str) -> None:
    assert (
        progress_report.get_timespan_string(timespan)
        ==
        (output_size, output_unit)
    )


@pytest.fixture()
def dummy_status_reports(
    _fake_time: None
) -> list[progress_report.DownloadStatusReport]:
    lines: list[progress_report.DownloadStatusReport] = []
    for i in range(10):
        dsr = progress_report.DownloadStatusReport(
            cast(download_job.DownloadManager, None)
        )
        dsr.name = f"dummy_dl_{i}"
        dsr.has_cmd = False
        dsr.has_dl = True
        dsr.download_begin_time = FAKE_TIME_ORIGIN
        dsr.downloaded_size = i
        dsr.expected_size = i * 2
        dsr.updates = deque([(FAKE_TIME_ORIGIN + datetime.timedelta(seconds=i), i)])
        lines.append(dsr)
    return lines


def test_append_status_report_line_strings_known_size(
    dummy_status_reports: list[progress_report.DownloadStatusReport]
) -> None:
    prm = progress_report.ProgressReportManager()
    prm._load_status_report_lines(dummy_status_reports)
    strs: list[str] = []
    prm._stringify_status_report_lines(prm.report_lines)
    prm._append_status_report_line_strings(prm.report_lines, strs)
    assert (
        strs[1]
        ==
        '01:00 m  1.00 B/s [==============>               ] 1 B /  2 B  eta 1.0 s  dummy_dl_1'
    )


def test_status_report_error(
    dummy_status_reports: list[progress_report.DownloadStatusReport]
) -> None:
    prm = progress_report.ProgressReportManager()
    dummy_status_reports[0].error = "test"
    dummy_status_reports[0].download_finished = True
    dummy_status_reports[0].download_end_time = dummy_status_reports[0].download_begin_time
    prm._load_status_report_lines(dummy_status_reports[0:1])
    strs: list[str] = []
    prm._stringify_status_report_lines(prm.newly_finished_report_lines)
    prm._append_status_report_line_strings(prm.newly_finished_report_lines, strs)
    assert (
        strs[0]
        ==
        '0.0 s  ??? B/s [         !! test !!         ] 0 B / 0 B  ---  dummy_dl_0'
    )


def test_status_report_cmd(
    dummy_status_reports: list[progress_report.DownloadStatusReport]
) -> None:
    prm = progress_report.ProgressReportManager()
    dummy_status_reports[0].has_cmd = True
    dummy_status_reports[0].download_end_time = dummy_status_reports[0].download_begin_time
    prm._load_status_report_lines(dummy_status_reports[0:1])
    strs: list[str] = []
    prm._stringify_status_report_lines(prm.report_lines)
    prm._append_status_report_line_strings(prm.report_lines, strs)
    assert (
        strs[0]
        ==
        '01:00 m  ??? B/s [<cmd running>=================] 0 B / 0 B  eta ???  dummy_dl_0'
    )


def test_status_report_cmd_no_dl(
    dummy_status_reports: list[progress_report.DownloadStatusReport]
) -> None:
    prm = progress_report.ProgressReportManager()
    dummy_status_reports[0].has_cmd = True
    dummy_status_reports[0].has_dl = False
    prm._load_status_report_lines(dummy_status_reports[0:1])
    strs: list[str] = []
    prm._stringify_status_report_lines(prm.report_lines)
    prm._append_status_report_line_strings(prm.report_lines, strs)
    assert (
        strs[0]
        ==
        '01:00 m  [<cmd running>                 ]   dummy_dl_0'
    )


def test_status_report_cmd_no_dl_other_dls_present(
    dummy_status_reports: list[progress_report.DownloadStatusReport]
) -> None:
    prm = progress_report.ProgressReportManager()
    dummy_status_reports[0].has_cmd = True
    dummy_status_reports[0].has_dl = False
    prm._load_status_report_lines(dummy_status_reports)
    strs: list[str] = []
    prm._stringify_status_report_lines(prm.report_lines)
    prm._append_status_report_line_strings(prm.report_lines, strs)
    assert (
        strs[0]
        ==
        '01:00 m           [<cmd running>                 ]                        dummy_dl_0'
    )
