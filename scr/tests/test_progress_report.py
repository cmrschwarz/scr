from .. import progress_report, download_job
from typing import cast, Any
import pytest
import datetime
from collections import deque


@pytest.mark.parametrize(('byte_size', 'output_size', 'output_unit'), [
    (1000, "1000", "B"),
    (-1, "-1", "B"),
    (0, "0", "B"),
    (1024, "1.00", "KiB"),
    (2**91, "2048.00", "YiB")
])
def test_get_byte_size_string_ints(byte_size: int, output_size: str, output_unit: str) -> None:
    assert (
        progress_report.get_byte_size_string(byte_size)
        ==
        (output_size, output_unit)
    )


@pytest.mark.parametrize(('timespan', 'output_size', 'output_unit'), [
    (0, "0.0", "s"),
    (-1, "-1.0", "s"),
    (60, "01:00", "m"),
    (59.99, "01:00", "m"),
    (59.49, "59.5", "s")
])
def test_get_timespan_string(timespan: float, output_size: str, output_unit: str) -> None:
    assert (
        progress_report.get_timespan_string(timespan)
        ==
        (output_size, output_unit)
    )


FAKE_TIME_ORIGIN = datetime.datetime.min
FAKE_TIME_NOW = (datetime.datetime.min + datetime.timedelta(seconds=60))


@pytest.fixture()
def _patch_datetime_now(monkeypatch: pytest.MonkeyPatch) -> None:
    class mydatetime(datetime.datetime):
        @classmethod
        def now(cls: Any, tz: Any = None) -> Any:
            return FAKE_TIME_NOW
    monkeypatch.setattr(datetime, 'datetime', mydatetime)


@pytest.fixture()
def dummy_status_reports(
    _patch_datetime_now: None
) -> list[progress_report.DownloadStatusReport]:
    lines: list[progress_report.DownloadStatusReport] = []
    for i in range(10):
        dsr = progress_report.DownloadStatusReport(
            cast(download_job.DownloadManager, None)
        )
        dsr.name = f"dummy_dl_{i}"
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
    prm._load_status_report_lines(dummy_status_reports[1:2])
    strs: list[str] = []
    prm._stringify_status_report_lines(prm.report_lines)
    prm._append_status_report_line_strings(prm.report_lines, strs)
    assert (
        strs[0]
        ==
        '01:00 m 1.00 B/s [==============>               ] '
        +
        '1 B / 2 B eta 1.0 s dummy_dl_1'
    )
