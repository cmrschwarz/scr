from typing import Optional, Union, cast
import math
import datetime
from collections import deque
import sys
import urllib
import os
from . import download_job, scr, utils

DOWNLOAD_STATUS_LOG_ELEMENTS_MIN = 5
DOWNLOAD_STATUS_LOG_ELEMENTS_MAX = 50
DOWNLOAD_STATUS_LOG_MAX_AGE = 10
DOWNLOAD_STATUS_NAME_LENGTH = 80
DOWNLOAD_STATUS_BAR_LENGTH = 30
DOWNLOAD_STATUS_REFRESH_INTERVAL = 0.2


def get_byte_size_string(size: Union[int, float]) -> tuple[str, str]:
    if size < 2**10:
        if type(size) is int:
            return f"{size}", "B"
        return f"{size:.2f}", "B"
    units = ["K", "M", "G", "T", "P", "E", "Z", "Y"]
    unit = int(math.log(size, 1024))
    if unit >= len(units):
        unit = len(units) - 1
    return f"{float(size)/2**(10 * unit):.2f}", f"{units[unit - 1]}iB"


def get_timespan_string(ts: float) -> tuple[str, str]:
    if ts < 60:
        return f"{ts:.1f}", "s"
    if ts < 3600:
        return f"{int(ts / 60):02}:{int(ts % 60):02}", "m"
    return f"{int(ts / 3600):02}:{int((ts % 3600) / 60):02}:{int(ts % 60):02}", "h"


def lpad(string: str, tgt_len: int) -> str:
    return " " * (tgt_len - len(string)) + string


def rpad(string: str, tgt_len: int) -> str:
    return string + " " * (tgt_len - len(string))


class DownloadStatusReport:
    name: str
    expected_size: Optional[int] = None
    downloaded_size: int = 0
    download_begin_time: datetime.datetime
    download_end_time: Optional[datetime.datetime] = None
    updates: deque[tuple[datetime.datetime, int]]
    download_finished: bool = False
    download_manager: 'download_job.DownloadManager'

    def __init__(self, download_manager: 'download_job.DownloadManager') -> None:
        self.updates = deque()
        self.download_manager = download_manager

    def gen_display_name(
        self,
        url: Optional[urllib.parse.ParseResult],
        filename: Optional[str],
        save_path: Optional[str]
    ) -> None:
        if save_path:
            if len(save_path) < DOWNLOAD_STATUS_NAME_LENGTH:
                self.name = save_path
                return
            self.name = os.path.basename(save_path)
        elif filename:
            self.name = filename
        elif url is not None:
            self.name = url.geturl()
        else:
            self.name = "<unnamed download>"
        self.name = utils.truncate(
            self.name, DOWNLOAD_STATUS_NAME_LENGTH
        )

    def submit_update(self, received_filesize: int) -> None:
        time = datetime.datetime.now()
        with self.download_manager.status_report_lock:
            self.downloaded_size += received_filesize
            self.updates.append((time, self.downloaded_size))
            drop_elem = False
            if len(self.updates) > DOWNLOAD_STATUS_LOG_ELEMENTS_MIN:
                if len(self.updates) > DOWNLOAD_STATUS_LOG_ELEMENTS_MAX:
                    drop_elem = True
                else:
                    age = (time - self.updates[0][0]).total_seconds()
                    if age > DOWNLOAD_STATUS_LOG_MAX_AGE:
                        drop_elem = True
            if drop_elem:
                self.updates.popleft()

    def enqueue(self) -> None:
        with self.download_manager.status_report_lock:
            self.download_manager.download_status_reports.append(self)
        self.download_begin_time = datetime.datetime.now()

    def finished(self) -> None:
        self.download_end_time = datetime.datetime.now()
        with self.download_manager.status_report_lock:
            self.download_finished = True


class StatusReportLine:
    name: str
    expected_size: Optional[int]
    downloaded_size: int
    speed_calculatable: bool
    download_begin: datetime.datetime
    download_end: Optional[datetime.datetime]
    speed_frame_time_begin: datetime.datetime
    speed_frame_time_end: datetime.datetime
    speed_frame_size_begin: int
    speed_frame_size_end: int
    star_pos: int = 1
    star_dir: int = 1
    last_line_length: int = 0
    finished: bool = False

    total_time_str: str
    total_time_u_str: str
    bar_str: str
    downloaded_size_str: str
    downloaded_size_u_str: str
    expected_size_str: str
    expected_size_u_str: str
    speed_str: str
    speed_u_str: str
    eta_str: str
    eta_u_str: str


def load_status_report_lines(dsr_list: list[DownloadStatusReport], report_lines: list[StatusReportLine]) -> None:
    # when we have more reports than report lines,
    # we remove the oldest finished report
    # if none are finished, we get more report lines
    if len(dsr_list) > len(report_lines):
        i = 0
        while i < len(dsr_list):
            if dsr_list[i].download_finished:
                del dsr_list[i]
                if len(dsr_list) == len(report_lines):
                    break
            else:
                i += 1
        else:
            for i in range(len(dsr_list) - len(report_lines)):
                report_lines.append(StatusReportLine())
    for i in range(len(report_lines)):
        rl = report_lines[i]
        dsr = dsr_list[i]
        rl.name = dsr.name
        rl.expected_size = dsr.expected_size
        rl.downloaded_size = dsr.downloaded_size
        rl.download_begin = dsr.download_begin_time
        rl.download_end = dsr.download_end_time
        rl.finished = dsr.download_finished
        if not len(dsr.updates):
            rl.speed_calculatable = False
        elif len(dsr.updates) == 1:
            rl.speed_calculatable = True
            rl.speed_frame_time_begin = dsr.download_begin_time
            rl.speed_frame_size_begin = 0
            rl.speed_frame_time_end = dsr.updates[0][0]
            rl.speed_frame_size_end = dsr.updates[0][1]
        else:
            rl.speed_calculatable = True
            rl.speed_frame_time_begin = dsr.updates[0][0]
            rl.speed_frame_size_begin = dsr.updates[0][1]
            rl.speed_frame_time_end = dsr.updates[-1][0]
            rl.speed_frame_size_end = dsr.updates[-1][1]


def stringify_status_report_lines(report_lines: list[StatusReportLine]) -> None:
    now = datetime.datetime.now()
    for rl in report_lines:
        if rl.expected_size and rl.expected_size >= rl.downloaded_size:
            frac = float(rl.downloaded_size) / rl.expected_size
            filled = int(frac * (DOWNLOAD_STATUS_BAR_LENGTH - 1))
            empty = DOWNLOAD_STATUS_BAR_LENGTH - filled - 1
            tip = ">" if rl.downloaded_size != rl.expected_size else "="
            rl.bar_str = "[" + "=" * filled + tip + " " * empty + "]"
        elif rl.finished:
            rl.bar_str = "[" + "*" * DOWNLOAD_STATUS_BAR_LENGTH + "]"
        else:
            left = rl.star_pos - 1
            right = DOWNLOAD_STATUS_BAR_LENGTH - 3 - left
            rl.bar_str = "[" + " " * left + "***" + " " * right + "]"
            if rl.star_pos == DOWNLOAD_STATUS_BAR_LENGTH - 2:
                rl.star_dir = -1
            elif rl.star_pos == 1:
                rl.star_dir = 1
            rl.star_pos += rl.star_dir
        if rl.finished:
            rl.expected_size = rl.downloaded_size
        rl.downloaded_size_str, rl.downloaded_size_u_str = (
            get_byte_size_string(rl.downloaded_size)
        )
        if rl.expected_size:
            rl.expected_size_str, rl.expected_size_u_str = (
                get_byte_size_string(rl.expected_size)
            )
        else:
            rl.expected_size_str, rl.expected_size_u_str = "???", "B"

        if rl.finished:
            assert rl.download_end
            rl.speed_frame_size_begin = 0
            rl.speed_frame_time_begin = rl.download_begin
            rl.speed_frame_size_end = rl.downloaded_size
            rl.speed_frame_time_end = rl.download_end
            rl.speed_calculatable = True
        else:
            rl.download_end = now
        if rl.speed_calculatable:
            duration = (
                (rl.speed_frame_time_end -
                    rl.speed_frame_time_begin).total_seconds()
            )
            handled_size = rl.speed_frame_size_end - rl.speed_frame_size_begin
            if handled_size == 0:
                speed = 0.0
                rl.eta_str, rl.eta_u_str = "???", " "
            else:
                speed = float(handled_size) / duration
                if rl.expected_size and rl.expected_size > rl.downloaded_size:
                    rl.eta_str, rl.eta_u_str = get_timespan_string(
                        (rl.expected_size - rl.downloaded_size) / speed
                    )
                elif rl.finished:
                    rl.eta_str, rl.eta_u_str = "---", "-"
                else:
                    rl.eta_str, rl.eta_u_str = "???", " "
            rl.speed_str, rl.speed_u_str = get_byte_size_string(speed)
            rl.speed_u_str += "/s"
        else:
            rl.speed_frame_time_end = now
            rl.eta_str, rl.eta_u_str = "???", " "
            rl.speed_str, rl.speed_u_str = "???", "B/s"

        rl.total_time_str, rl.total_time_u_str = get_timespan_string(
            (rl.download_end - rl.download_begin).total_seconds()
        )


def append_status_report_line_strings(
    report_lines: list[StatusReportLine], report: list[str]
) -> None:
    def field_len_max(field_name: str) -> int:
        return max(map(lambda rl: len(rl.__dict__[field_name]), report_lines))

    name_lm = field_len_max("name")
    total_time_lm = field_len_max("total_time_str")
    total_time_u_lm = field_len_max("total_time_u_str")
    downloaded_size_lm = field_len_max("downloaded_size_str")
    downloaded_size_u_lm = field_len_max("downloaded_size_u_str")
    expected_size_lm = field_len_max("expected_size_str")
    expected_size_u_lm = field_len_max("expected_size_u_str")
    eta_lm = field_len_max("eta_str")
    eta_u_lm = field_len_max("eta_u_str")
    speed_lm = field_len_max("speed_str")
    speed_u_lm = field_len_max("speed_u_str")

    for rl in report_lines:
        line = ""

        line += lpad(rl.total_time_str, total_time_lm) + " "
        line += rpad(rl.total_time_u_str, total_time_u_lm) + " "

        line += lpad(rl.speed_str, speed_lm) + " "
        line += rpad(rl.speed_u_str, speed_u_lm) + " "

        line += rl.bar_str + " "

        line += lpad(rl.downloaded_size_str, downloaded_size_lm) + " "
        line += rpad(rl.downloaded_size_u_str, downloaded_size_u_lm)
        line += " / "
        line += lpad(rl.expected_size_str, expected_size_lm) + " "
        line += rpad(rl.expected_size_u_str, expected_size_u_lm) + " "

        line += "eta "
        line += lpad(rl.eta_str, eta_lm)
        line += " " + rpad(rl.eta_u_str, eta_u_lm) + " "

        # if everybody is done, we don't need to pad for this anymore
        line += rl.name

        if len(line) < rl.last_line_length:
            lll = len(line)
            # fill with spaces to clear previous line
            line += " " * (rl.last_line_length - lll)
            rl.last_line_length = lll
        else:
            rl.last_line_length = len(line)
        report.append(line)


def print_status_report(report_lines: list[StatusReportLine], prev_report_line_count: int) -> int:
    stringify_status_report_lines(report_lines)
    report_line_strings: list[str] = []
    append_status_report_line_strings(
        report_lines, report_line_strings
    )

    report = ""
    if prev_report_line_count:
        report += f"\x1B[{prev_report_line_count}F"

    max_cols = os.get_terminal_size().columns
    if max_cols < 5:
        # don't bother
        return prev_report_line_count

    for l in report_line_strings:
        if len(l) < max_cols:
            report += l + " " * (max_cols - len(l)) + "\n"
        else:
            report += l[0:max_cols-3] + "...\n"
    sys.stdout.write(report)
    return len(report_lines)
