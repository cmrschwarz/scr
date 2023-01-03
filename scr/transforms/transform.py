from abc import ABC, abstractmethod
from scr import chain
from scr.match import Match, MatchEager, MatchConcrete


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
    def apply(self, c: 'chain.Chain', m: Match) -> Match:
        raise NotImplementedError


class TransformEager(Transform):
    @abstractmethod
    def apply_concrete(self, m: MatchConcrete) -> MatchEager:
        raise NotImplementedError

    def apply(self, c: 'chain.Chain', m: Match) -> Match:
        return m.apply_eager(c.ctx.executor, self.apply_concrete)


class TransformLazy(Transform):
    @abstractmethod
    def apply_concrete(self, m: MatchConcrete) -> MatchEager:
        raise NotImplementedError

    def apply(self, c: 'chain.Chain', m: Match) -> Match:
        return m.apply_lazy(c.ctx.executor, self.apply_concrete)
