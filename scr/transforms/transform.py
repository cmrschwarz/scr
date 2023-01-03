from abc import ABC, abstractmethod
import scr.chain
import scr.match


class Transform(ABC):
    label: str

    def __init__(self, label: str) -> None:
        self.label = label

    @staticmethod
    @abstractmethod
    def name_matches(name: str) -> bool:
        raise NotImplementedError

    def is_accepting(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def apply(self, c: scr.chain.Chain, m: scr.match.Match) -> scr.match.Match:
        raise NotImplementedError


class TransformEager(Transform):
    @abstractmethod
    def apply_concrete(self, m: scr.match.MatchConcrete) -> scr.match.MatchEager:
        raise NotImplementedError

    def apply(self, c: scr.chain.Chain, m: scr.match.Match) -> scr.match.Match:
        return m.apply_eager(c.ctx.executor, self.apply_concrete)
