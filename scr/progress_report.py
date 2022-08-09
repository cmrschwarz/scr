from typing import Optional, Union, cast
import math
import datetime
from collections import deque
import sys
import urllib
import os
from . import download_job, utils

DOWNLOAD_STATUS_LOG_ELEMENTS_MIN = 5
DOWNLOAD_STATUS_LOG_ELEMENTS_MAX = 50
DOWNLOAD_STATUS_LOG_MAX_AGE = 10
DOWNLOAD_STATUS_NAME_LENGTH = 80
DOWNLOAD_STATUS_BAR_LENGTH = 30
DOWNLOAD_STATUS_REFRESH_INTERVAL = 0.2
DOWNLOAD_STATUS_KEEP_FINISHED = True
DEFAULT_MAX_TERMINAL_LINE_LENGTH = 120

CMD_RUNNING_HINT = "(cmd running...)"


def get_byte_size_string(size: Union[int, float]) -> tuple[str, str]:
    if size < 2**10:
        if type(size) is int:
            return f"{size}", " B"
        return f"{size:.2f}", " B"
    units = ["K", "M", "G", "T", "P", "E", "Z", "Y"]
    unit = int(math.log(size, 1024))
    if unit >= len(units):
        unit = len(units)
    return f"{float(size)/2**(10 * unit):.2f}", f" {units[unit - 1]}iB"


def get_timespan_string(ts: float) -> tuple[str, str]:
    if round(ts * 10) < 600:
        return f"{ts:.1f}", " s"
    if round(ts) == 60:
        return "01:00", " m"
    if ts < 3600:
        return f"{int(ts / 60):02}:{round(ts % 60):02}", " m"
    return f"{int(ts / 3600):02}:{int((ts % 3600) / 60):02}:{int(ts % 60):02}", " h"


def lpad(string: str, tgt_len: int) -> str:
    return " " * (tgt_len - len(string)) + string


def rpad(string: str, tgt_len: int) -> str:
    return string + " " * (tgt_len - len(string))


def pad(string: str, tgt_len: int) -> str:
    lpad = int((tgt_len - len(string)) / 2)
    rpad = tgt_len - len(string) - lpad
    return " " * lpad + string + " " * rpad


class DownloadStatusReport:
    name: str
    has_dl: bool = False
    has_cmd: bool = False
    expected_size: Optional[int] = None
    downloaded_size: int = 0
    download_begin_time: datetime.datetime
    download_end_time: Optional[datetime.datetime] = None
    updates: deque[tuple[datetime.datetime, int]]
    download_finished: bool = False
    download_manager: 'download_job.DownloadManager'
    error: Optional[str] = None

    def __init__(self, download_manager: 'download_job.DownloadManager') -> None:
        self.updates = deque()
        self.download_manager = download_manager

    def gen_display_name(
        self,
        url: Optional[urllib.parse.ParseResult],
        filename: Optional[str],
        save_path: Optional[str],
        shell_cmd: Optional[str],
    ) -> None:
        self.has_cmd = shell_cmd is not None
        self.has_dl = url is not None
        if save_path:
            if len(save_path) < DOWNLOAD_STATUS_NAME_LENGTH:
                self.name = save_path
                return
            self.name = os.path.basename(save_path)
        elif filename:
            self.name = filename
        elif url is not None:
            self.name = url.geturl()
        elif shell_cmd is not None:
            self.name = shell_cmd
        elif self.has_dl:
            self.name = "<unnamed download>"
        else:
            self.name = "<shell command>"
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
    has_cmd: bool
    has_dl: bool
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
    error: Optional[str] = None

    total_time_str: str
    total_time_u_str: str
    bar_str: str
    downloaded_size_str: str
    downloaded_size_u_str: str
    size_separator_str: str
    expected_size_str: str
    expected_size_u_str: str
    speed_str: str
    speed_u_str: str
    eta_label_str: str
    eta_str: str
    eta_u_str: str


class ProgressReportManager:
    finished_report_lines: list[StatusReportLine]
    finished_report_lines_max_length: int = 0
    newly_finished_report_lines: list[StatusReportLine]
    report_lines: list[StatusReportLine]
    prev_report_line_count: int
    prev_terminal_column_count: int = 0

    total_time_lm: int = 0
    total_time_u_lm: int = 0
    downloaded_size_lm: int = 0
    downloaded_size_u_lm: int = 0
    size_separator_lm: int = 0
    expected_size_lm: int = 0
    expected_size_u_lm: int = 0
    eta_label_lm: int = 0
    eta_lm: int = 0
    eta_u_lm: int = 0
    speed_lm: int = 0
    speed_u_lm: int = 0
    lms_changed: bool = False

    def __init__(self) -> None:
        self.report_lines = []
        self.finished_report_lines = []
        self.newly_finished_report_lines = []
        self.prev_report_line_count = 0

    def load_status(self, download_manager: 'download_job.DownloadManager') -> None:
        with download_manager.status_report_lock:
            self._load_status_report_lines(
                download_manager.download_status_reports
            )

    def updates_remaining(self) -> bool:
        return (
            len(self.report_lines) > 0
            or
            len(self.newly_finished_report_lines) > 0
        )

    def _load_status_report_lines(self, dsr_list: list[DownloadStatusReport]) -> None:
        if (not DOWNLOAD_STATUS_KEEP_FINISHED) and len(dsr_list) > len(self.report_lines):
            # when we have more reports than report lines,
            # we remove the oldest finished report
            # if none are finished, we get more report lines
            i = 0
            while i < len(dsr_list):
                if dsr_list[i].download_finished:
                    del dsr_list[i]
                    if len(dsr_list) == len(self.report_lines):
                        break
                else:
                    i += 1
        for i in range(len(dsr_list) - len(self.report_lines)):
            self.report_lines.append(StatusReportLine())
        for i in range(len(self.report_lines)):
            rl = self.report_lines[i]
            dsr = dsr_list[i]
            rl.name = dsr.name
            rl.has_cmd = dsr.has_cmd
            rl.has_dl = dsr.has_dl
            rl.expected_size = dsr.expected_size
            rl.downloaded_size = dsr.downloaded_size
            rl.download_begin = dsr.download_begin_time
            rl.download_end = dsr.download_end_time
            rl.error = dsr.error
            rl.finished = dsr.download_finished
            if not len(dsr.updates) or not rl.has_dl:
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
        if DOWNLOAD_STATUS_KEEP_FINISHED:
            i = 0
            while i < len(dsr_list):
                if dsr_list[i].download_finished:
                    self.newly_finished_report_lines.append(self.report_lines[i])
                    del dsr_list[i]
                    del self.report_lines[i]
                else:
                    i += 1

    def _stringify_status_report_lines(self, report_lines: list[StatusReportLine]) -> None:
        now = datetime.datetime.now()
        for rl in report_lines:
            done = (rl.downloaded_size == rl.expected_size or not rl.has_dl)
            if rl.error is not None:
                if not rl.finished:
                    rl.finished = True
                    rl.download_end = now
                err_str = utils.truncate(rl.error, DOWNLOAD_STATUS_BAR_LENGTH - 8)
                rl.bar_str = "[" + pad("!! " + err_str + " !!", DOWNLOAD_STATUS_BAR_LENGTH - 2) + "]"
            elif rl.expected_size and rl.expected_size >= rl.downloaded_size and (not done or not rl.has_cmd):
                frac = float(rl.downloaded_size) / rl.expected_size
                filled = int(frac * (DOWNLOAD_STATUS_BAR_LENGTH - 1))
                empty = DOWNLOAD_STATUS_BAR_LENGTH - filled - 1
                tip = ">" if not done else "="
                rl.bar_str = "[" + "=" * filled + tip + " " * empty + "]"
            elif rl.finished:
                rl.bar_str = "[" + "=" * DOWNLOAD_STATUS_BAR_LENGTH + "]"
            else:
                if rl.has_cmd and done:
                    middle = "<cmd running>"
                else:
                    middle = "***"

                if done and rl.has_dl:
                    blank = "="
                else:
                    blank = " "
                left = rl.star_pos - 1
                right = DOWNLOAD_STATUS_BAR_LENGTH - len(middle) - left
                rl.bar_str = "[" + blank * left + middle + blank * right + "]"
                if rl.star_pos == DOWNLOAD_STATUS_BAR_LENGTH - len(middle) + 1:
                    rl.star_dir = -1
                elif rl.star_pos == 1:
                    rl.star_dir = 1
                rl.star_pos += rl.star_dir

            if rl.finished:
                rl.expected_size = rl.downloaded_size

            if rl.finished:
                assert rl.download_end
                rl.speed_frame_size_begin = 0
                rl.speed_frame_time_begin = rl.download_begin
                rl.speed_frame_size_end = rl.downloaded_size
                rl.speed_frame_time_end = rl.download_end
                rl.speed_calculatable = rl.has_dl
            else:
                rl.download_end = now

            if not rl.has_dl:
                rl.size_separator_str = ""
                rl.speed_str, rl.speed_u_str = "", ""
                if not rl.finished:
                    rl.eta_label_str = ""
                    rl.eta_str, rl.eta_u_str = "", ""
                else:
                    rl.eta_label_str = "  ---"
                    rl.eta_str, rl.eta_u_str = " ", ""
                rl.downloaded_size_str, rl.downloaded_size_u_str = "", ""
                rl.expected_size_str, rl.expected_size_u_str = "", ""
            else:
                if rl.finished:
                    rl.eta_label_str = "  ---"
                    rl.eta_str, rl.eta_u_str = "", ""
                else:
                    rl.eta_label_str = "  eta "
                rl.downloaded_size_str, rl.downloaded_size_u_str = (
                    get_byte_size_string(rl.downloaded_size)
                )
                if rl.expected_size is not None:
                    rl.expected_size_str, rl.expected_size_u_str = (
                        get_byte_size_string(rl.expected_size)
                    )
                else:
                    rl.expected_size_str, rl.expected_size_u_str = "???", ""

                rl.size_separator_str = " / "
                if rl.speed_calculatable:
                    duration = (
                        (rl.speed_frame_time_end -
                            rl.speed_frame_time_begin).total_seconds()
                    )
                    handled_size = rl.speed_frame_size_end - rl.speed_frame_size_begin
                    if duration < sys.float_info.epsilon:
                        rl.speed_str, rl.speed_u_str = "???", " B/s"
                        if not rl.finished:
                            rl.eta_str, rl.eta_u_str = "???", ""
                    else:
                        if handled_size == 0:
                            speed = 0.0
                            if not rl.finished:
                                rl.eta_str, rl.eta_u_str = "???", ""
                        else:
                            speed = float(handled_size) / duration
                            if not rl.finished:
                                if rl.expected_size and rl.expected_size > rl.downloaded_size:
                                    rl.eta_str, rl.eta_u_str = get_timespan_string(
                                        (rl.expected_size - rl.downloaded_size) / speed
                                    )
                                else:
                                    rl.eta_str, rl.eta_u_str = "???", ""
                        rl.speed_str, rl.speed_u_str = get_byte_size_string(speed)
                        rl.speed_u_str = rl.speed_u_str + "/s"
                else:
                    rl.speed_frame_time_end = now
                    rl.speed_str, rl.speed_u_str = "???", " B/s"
                    if not rl.finished:
                        rl.eta_str, rl.eta_u_str = "???", ""
                rl.speed_str = " " + rl.speed_str

            rl.total_time_str, rl.total_time_u_str = get_timespan_string(
                (rl.download_end - rl.download_begin).total_seconds()
            )

    def _update_field_len_max(
        self, report_lines: list[StatusReportLine], field_name: str
    ) -> None:
        rls_lm = max(map(
            lambda rl: len(rl.__dict__[field_name + "_str"]), report_lines
        ), default=0)
        if rls_lm > cast(int, self.__dict__.get(field_name + "_lm", 0)):
            self.__dict__[field_name + "_lm"] = rls_lm
            self.lms_changed = True

    def _append_status_report_line_strings(
        self, report_lines: list[StatusReportLine], report: list[str]
    ) -> None:

        self._update_field_len_max(report_lines, "total_time")
        self._update_field_len_max(report_lines, "total_time_u")
        self._update_field_len_max(report_lines, "downloaded_size")
        self._update_field_len_max(report_lines, "downloaded_size_u")
        self._update_field_len_max(report_lines, "size_separator")
        self._update_field_len_max(report_lines, "expected_size")
        self._update_field_len_max(report_lines, "expected_size_u")
        self._update_field_len_max(report_lines, "eta_label")
        self._update_field_len_max(report_lines, "eta")
        self._update_field_len_max(report_lines, "eta_u")
        self._update_field_len_max(report_lines, "speed")
        self._update_field_len_max(report_lines, "speed_u")

        for rl in report_lines:
            line = ""

            line += lpad(rl.total_time_str, self.total_time_lm)
            line += rpad(rl.total_time_u_str, self.total_time_u_lm)

            line += " "

            line += lpad(rl.speed_str, self.speed_lm)
            line += rpad(rl.speed_u_str, self.speed_u_lm)

            line += " " + rl.bar_str + " "

            line += lpad(rl.downloaded_size_str, self.downloaded_size_lm)
            line += rpad(rl.downloaded_size_u_str, self.downloaded_size_u_lm)
            line += pad(rl.size_separator_str, self.size_separator_lm)
            line += lpad(rl.expected_size_str, self.expected_size_lm)
            line += rpad(rl.expected_size_u_str, self.expected_size_u_lm)

            line += pad(rl.eta_label_str, self.eta_label_lm)
            line += lpad(rl.eta_str, self.eta_lm)
            line += rpad(rl.eta_u_str, self.eta_u_lm)

            line += "  "
            line += rl.name

            if len(line) < rl.last_line_length:
                lll = len(line)
                # fill with spaces to clear previous line
                line += " " * (rl.last_line_length - lll)
                rl.last_line_length = lll
            else:
                rl.last_line_length = len(line)
            report.append(line)

    def print_status_report(self) -> None:
        try:
            max_cols = os.get_terminal_size().columns
            if max_cols < 5:
                # don't bother
                return
        except IOError:
            max_cols = DEFAULT_MAX_TERMINAL_LINE_LENGTH

        # even if the size just grew we are doing this since the terminal
        # might have messed up our output
        update_finished = (max_cols != self.prev_terminal_column_count)
        report_lines = self.newly_finished_report_lines + self.report_lines
        self._stringify_status_report_lines(report_lines)
        report_line_strings: list[str] = []
        self._append_status_report_line_strings(
            self.newly_finished_report_lines,
            report_line_strings
        )
        max_len_nfrls = max((len(rls) for rls in report_line_strings), default=0)
        self.finished_report_lines_max_length = max(
            max_len_nfrls,
            self.finished_report_lines_max_length
        )
        self._append_status_report_line_strings(
            self.report_lines,
            report_line_strings
        )
        if self.lms_changed:
            self._stringify_status_report_lines(self.finished_report_lines)
            update_finished = True
            self.lms_changed = False

        report_lines_to_rewrite = self.prev_report_line_count
        if update_finished:
            finished_rls: list[str] = []
            self._append_status_report_line_strings(
                self.finished_report_lines,
                finished_rls
            )
            finished_rls.extend(report_line_strings)
            report_line_strings = finished_rls
            report_lines_to_rewrite += len(self.finished_report_lines)
        report = ""
        if report_lines_to_rewrite:
            report += f"\x1B[{report_lines_to_rewrite}F"
        for rls in report_line_strings:
            rls_len = len(rls)
            if rls_len < max_cols:
                report += rls + " " * (max_cols - len(rls)) + "\n"
            else:
                report += rls[0:max_cols-3] + "...\n"
        sys.stdout.write(report)
        self.finished_report_lines.extend(self.newly_finished_report_lines)
        self.newly_finished_report_lines.clear()
        self.prev_report_line_count = len(self.report_lines)
        self.prev_terminal_column_count = max_cols
