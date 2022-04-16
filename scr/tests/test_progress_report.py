from .. import progress_report
import pytest


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
