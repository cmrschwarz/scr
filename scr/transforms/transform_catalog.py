from typing import Type

from scr.transforms import transform, regex, sleep

TRANSFORM_CATALOG: list[Type['transform.Transform']] = [
    regex.Regex,
    sleep.Sleep
]
