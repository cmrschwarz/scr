from typing import Optional


def str_prefixes(str: str) -> list[str]:
    return [str[:i] for i in range(len(str), 0, -1)]


TRUE_INDICATING_STRINGS = set([*str_prefixes("true"), *str_prefixes("yes"), "1"])
FALSE_INDICATING_STRINGS = set([*str_prefixes("false"), *str_prefixes("no"), "0"])


def try_parse_bool(val: str) -> Optional[bool]:
    if val in TRUE_INDICATING_STRINGS:
        return True
    if val in FALSE_INDICATING_STRINGS:
        return False
    return None
