from .. import progress_report
import pytest


@pytest.mark.parametrize("byte_size,output_size,output_unit", [
    (1000, "1000", "B"),
    (-1, "-1", "B"),
    (1024, "1", "KiB"),
    (0, "0", "B"),
    (2**91, "2097152.00", "YiB")
])
def test_get_byte_size_string_ints(byte_size: int, output_size: str, output_unit: str) -> None:
    assert (
        progress_report.get_byte_size_string(byte_size)
        ==
        (output_size, output_unit)
    )
