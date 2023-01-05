from typing import Optional, Iterable
from abc import ABC, abstractmethod
import itertools


class RangeSpecParseException(Exception):
    pass


class RangeSpec(ABC):
    def __init__(self) -> None:
        pass

    @abstractmethod
    def explicit_max(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def has_unbounded_max(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def iter(self, implicit_max: int) -> Iterable[int]:
        raise NotImplementedError


class RangeSpecValue(RangeSpec):
    value: int

    def __init__(self, value: int) -> None:
        super().__init__()
        self.value = value

    def explicit_max(self) -> int:
        return self.value + 1

    def has_unbounded_max(self) -> bool:
        return False

    def iter(self, implicit_max: int) -> Iterable[int]:
        yield self.value


class RangeSpecBounds(RangeSpec):
    min: Optional[int]
    max: Optional[int]

    def __init__(self, min: Optional[int], max: Optional[int]) -> None:
        super().__init__()
        self.min = min
        self.max = max

    def explicit_max(self) -> int:
        if self.max is not None:
            return self.max
        if self.min is not None:
            return self.min
        return 0

    def has_unbounded_max(self) -> bool:
        return self.max is not None

    def iter(self, implicit_max: int) -> Iterable[int]:
        it_min = self.min if self.min is not None else 0
        it_max = self.max if self.max is not None else implicit_max
        return range(it_min, it_max)


class RangeSpecAggregate(RangeSpec):
    subranges: list[RangeSpec]

    def __init__(self, subranges: list[RangeSpec]) -> None:
        super().__init__()
        self.subranges = subranges

    def explicit_max(self) -> int:
        em = 0
        for sr in self.subranges:
            sr_em = sr.explicit_max()
            if sr_em > 0:
                em = sr_em
        return em

    def has_unbounded_max(self) -> bool:
        for sr in self.subranges:
            if sr.has_unbounded_max():
                return True
        return False

    def iter(self, implicit_max: int) -> Iterable[int]:
        return itertools.chain(*[sr.iter(implicit_max) for sr in self.subranges])


class RangeSpecExclude(RangeSpec):
    base: RangeSpec
    exclude: RangeSpec

    def __init__(self, base: RangeSpec, exclude: RangeSpec):
        super().__init__()
        self.base = base
        self.exclude = exclude

    def explicit_max(self) -> int:
        base_em = self.base.explicit_max()
        exclusions = sorted(self.exclude.iter(base_em), reverse=True)
        for ex in exclusions:
            if base_em > ex:
                return base_em
            if base_em < ex:
                continue
            if base_em == 0:
                return 0
            base_em -= 1
        return base_em

    def has_unbounded_max(self) -> bool:
        return self.base.has_unbounded_max() and not self.exclude.has_unbounded_max()

    def iter(self, implicit_max: int) -> Iterable[int]:
        return ({*self.base.iter(implicit_max)} - {*self.exclude.iter(implicit_max)})


def parse_range_spec_int(v: str, parent_range: Optional[str]) -> int:
    try:
        res = int(v)
        if res < 0:
            raise RangeSpecParseException("range spec contains negative integer '{v}'")
        return res
    except ValueError:
        if parent_range is None:
            raise RangeSpecParseException("failed to parse '{v}' as an integer")
        raise RangeSpecParseException(f"failed to parse '{v}' as an integer in '{parent_range}'")


def parse_range_spec(rs: str, parent_range: Optional[str] = None) -> RangeSpec:
    rs = rs.strip()
    if rs == "":
        if parent_range is None:
            raise RangeSpecParseException("invalid empty range")
        raise RangeSpecParseException("unexpected empty subrange in '{parent_range}'")

    subranges = rs.split(",")
    if len(subranges) != 1:
        subranges_rs = [parse_range_spec(sr, rs) for sr in subranges]
        return RangeSpecAggregate(subranges_rs)

    esc_split = rs.split("^")
    if len(esc_split) == 2:
        base = parse_range_spec(esc_split[0], rs)
        exclude = parse_range_spec(esc_split[0], rs)
        return RangeSpecExclude(base, exclude)
    if len(esc_split) != 1:
        raise RangeSpecParseException(f"multiple occurences of '^' in '{rs}'")

    minus_split = rs.split("-")
    if len(minus_split) == 2:
        min_bound = minus_split[0].strip()
        max_bound = minus_split[1].strip()
        r_min = parse_range_spec_int(min_bound, rs) if min_bound else None
        r_max = parse_range_spec_int(max_bound, rs) if min_bound else None
        return RangeSpecBounds(r_min, r_max)
    if len(esc_split) != 1:
        raise RangeSpecParseException(f"multiple occurences of '-' in '{rs}'")

    return RangeSpecValue(parse_range_spec_int(rs, parent_range))
