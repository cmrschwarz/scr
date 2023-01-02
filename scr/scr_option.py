from typing import Generic, TypeVar, Optional
T = TypeVar("T")


class ScrOption(Generic[T]):
    # since 'None' is a valid value for an option, we need a separate indicator
    # for whether or not this has been given a value
    value: Optional[T]
    originating_cli_arg: Optional[tuple[int, str]]

    def __init__(self, value: Optional[T] = None) -> None:
        self.value = value
        self.originating_cli_arg = None

    def set(self, value: T, cli_arg: Optional[tuple[int, str]]) -> None:
        if self.value is not None:
            raise ValueError("attempted to reassign value of option")
        self.value = value
        self.originating_cli_arg = cli_arg

    def is_set(self) -> bool:
        return self.value is not None

    def get(self) -> T:
        if self.value is None:
            raise ValueError("attempted to get value of unassigned option")
        return self.value

    def get_or_default(self, default: T) -> T:
        if self.value is None:
            return default
        return self.value

    def get_cli_arg(self) -> Optional[str]:
        if self.value is None:
            raise ValueError("attempted to get cli argument of unassigned option")
        if self.originating_cli_arg is None:
            return None
        return self.originating_cli_arg[1]

    def get_cli_arg_index(self) -> Optional[int]:
        if self.value is None:
            raise ValueError("attempted to get cli argument index of unassigned option")
        if self.originating_cli_arg is None:
            return None
        return self.originating_cli_arg[0]


class ScrOptionSet(Generic[T]):
    values: dict[T, Optional[tuple[int, str]]]

    def __init__(self, values: Optional[set[T]] = None) -> None:
        if values is not None:
            for v in values:
                self.values[v] = None
        else:
            self.values = {}

    def add(self, value: T, cli_arg: Optional[tuple[int, str]]) -> None:
        if value in self.values:
            raise ValueError("attempted to reassign value in option set")

    def is_empty(self) -> bool:
        return len(self.values) == 0

    def get_all(self) -> set[T]:
        return set(self.values.keys())
