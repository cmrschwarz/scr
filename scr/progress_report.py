from typing import Optional
import datetime


class JobProgressReport:
    name: str
    begin: datetime.datetime
    end: Optional[datetime.datetime] = None
    speed: Optional[float] = None  # B/s
    eta: Optional[datetime.datetime] = None
    progress: Optional[float] = None  # [0.0, 1.0]
    error: Optional[str] = None
    expected_size: Optional[int] = None
    handled_size: int = 0

    def __init__(self, name: str):
        self.name = name
        self.begin = datetime.datetime.now()


SIZED_JOB_REPORTING_FREQUENCY = datetime.timedelta(seconds=0.1)
SIZED_JOB_DATA_POINT_COUNT = 7


class SizedJobProgressReport(JobProgressReport):
    reported_sizes: list[tuple[datetime.datetime, int]]

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.reported_sizes = []

    def update_speed(self, now: datetime.datetime) -> None:
        first = self.reported_sizes[0]
        last = self.reported_sizes[-1]
        self.speed = (last[1] - first[1]) / (last[0] - first[0]).total_seconds()
        if self.expected_size is not None:
            self.eta = now + datetime.timedelta(
                seconds=self.speed * float(self.expected_size - self.handled_size)
            )

    def set_expected_size(self, expected_size: int) -> None:
        self.expected_size = expected_size
        self.update_speed(datetime.datetime.now())

    def report_handled_size(self, handled_size: int) -> None:
        now = datetime.datetime.now()
        self.handled_size = handled_size
        if (now - self.reported_sizes[-1][0]) < SIZED_JOB_REPORTING_FREQUENCY:
            return
        if len(self.reported_sizes) < SIZED_JOB_DATA_POINT_COUNT:
            self.reported_sizes.append((now, handled_size))
            if len(self.reported_sizes) > 1:
                self.update_speed(now)
        self.reported_sizes.pop(0)
        self.reported_sizes.append((now, handled_size))
        self.update_speed(now)


class ProgressReporter:
    pass
