from dataclasses import dataclass
from typing import Generic, TypeVar, Optional, Union, Any
T = TypeVar("T")
D = TypeVar("D")


@dataclass(slots=True)
class CliArgRef:
    arg: str
    arg_idx: int


class ScrOptionReassignmentError(Exception):
    originating_cli_arg: Optional[CliArgRef]

    def __init__(self, originating_cli_arg: Optional[CliArgRef], *args: Any) -> None:
        super().__init__(*args)
        self.originating_cli_arg = originating_cli_arg


class ScrOption(Generic[T]):
    value: Optional[T]
    originating_cli_arg: Optional[CliArgRef]

    def __init__(self, value: Optional[T] = None) -> None:
        self.value = value
        self.originating_cli_arg = None

    def set(self, value: T, cli_arg: Optional[CliArgRef] = None) -> None:
        if self.value is not None:
            raise ScrOptionReassignmentError(self.originating_cli_arg, "attempted to reassign value of option")
        self.value = value
        self.originating_cli_arg = cli_arg

    def is_set(self) -> bool:
        return self.value is not None

    def get(self) -> T:
        if self.value is None:
            raise ValueError("attempted to get value of unassigned option")
        return self.value

    def get_or_default(self, default: D) -> Union[T, D]:
        if self.value is not None:
            return self.value
        return default

    def get_cli_arg_ref(self) -> Optional[CliArgRef]:
        if self.value is None:
            raise ValueError("attempted to get cli argument of unassigned option")
        if self.originating_cli_arg is None:
            return None
        return self.originating_cli_arg


class ScrOptionSet(Generic[T]):
    values: dict[T, Optional[CliArgRef]]

    def __init__(self, values: Optional[set[T]] = None) -> None:
        if values is not None:
            for v in values:
                self.values[v] = None
        else:
            self.values = {}

    def add(self, value: T, cli_arg: Optional[CliArgRef]) -> None:
        if value in self.values:
            raise ScrOptionReassignmentError(self.values[value], "attempted to reassign value in option set")

    def is_empty(self) -> bool:
        return len(self.values) == 0

    def get_all(self) -> set[T]:
        return set(self.values.keys())

    def get_cli_arg(self, key: T) -> Optional[CliArgRef]:
        return self.values[key]
