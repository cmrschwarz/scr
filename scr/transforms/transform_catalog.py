from typing import Type

from scr.transforms import transform, regex, sleep, next, merge, print, split

TRANSFORM_CATALOG: list[Type['transform.Transform']] = [
    regex.Regex,
    sleep.Sleep,
    print.Print,
    merge.Merge,
    next.Next,
    split.Split,
]
