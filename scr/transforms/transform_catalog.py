from typing import Type

from scr.transforms import transform, regex

TRANSFORM_CATALOG: list[Type[transform.Transform]] = [
    regex.Regex
]
