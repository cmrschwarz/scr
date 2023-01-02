from abc import ABC, abstractmethod
from scr import match


class Transform(ABC):
    @staticmethod
    @abstractmethod
    def name_matches(name: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def is_accepting(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def apply(self, matches: list[match.Match]) -> list[match.Match]:
        raise NotImplementedError
