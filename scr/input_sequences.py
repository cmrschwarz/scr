from typing import Iterable, TypeVar

from .definitions import *


def prefixes(str: str) -> set[str]:
    return set(str[:i] for i in range(len(str), 0, -1))


def set_join(*args: Iterable['T']) -> set['T']:
    res: set[T] = set()
    for s in args:
        res.update(s)
    return res


class OptionIndicatingStrings:
    representative: str
    matching: set[str]

    def __init__(self, representative: str, *args: set[str]) -> None:
        self.representative = representative
        if args:
            self.matching = set_join(*args)
        else:
            self.matching = prefixes(representative)


YES_INDICATING_STRINGS = OptionIndicatingStrings(
    "yes",
    prefixes("yes"), prefixes("true"), {"1", "+"}
)
NO_INDICATING_STRINGS = OptionIndicatingStrings(
    "no", prefixes("no"), prefixes("false"), {"0", "-"}
)
SKIP_INDICATING_STRINGS = OptionIndicatingStrings("skip")
CHAIN_SKIP_INDICATING_STRINGS = OptionIndicatingStrings("chainskip")
EDIT_INDICATING_STRINGS = OptionIndicatingStrings("edit")
DOC_SKIP_INDICATING_STRINGS = OptionIndicatingStrings("docskip")
INSPECT_INDICATING_STRINGS = OptionIndicatingStrings("inspect")
ACCEPT_CHAIN_INDICATING_STRINGS = OptionIndicatingStrings("acceptchain")
