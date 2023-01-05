from abc import ABC, abstractmethod
from scr import chain, chain_prototype, match
from typing import Optional


class TransformValueError(Exception):
    pass


class Transform(ABC):
    label: str

    def __init__(self, label: str) -> None:
        self.label = label

    @staticmethod
    @abstractmethod
    def create(label: str, value: Optional[str]) -> 'Transform':
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def name_matches(name: str) -> bool:
        raise NotImplementedError

    def is_accepting(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def apply(self, c: 'chain.Chain', m: 'match.Match') -> 'match.Match':
        raise NotImplementedError

    def get_next_chain(self, current: 'chain_prototype.ChainPrototype') -> Optional['chain_prototype.ChainPrototype']:
        return current


class TransformEager(Transform):
    @abstractmethod
    def apply_concrete(self, m: 'match.MatchConcrete') -> 'match.MatchEager':
        raise NotImplementedError

    def apply(self, c: 'chain.Chain', m: 'match.Match') -> 'match.Match':
        return m.apply_eager(c.ctx.executor, self.apply_concrete)


class TransformLazy(Transform):
    @abstractmethod
    def apply_concrete(self, m: 'match.MatchConcrete') -> 'match.MatchEager':
        raise NotImplementedError

    def apply(self, c: 'chain.Chain', m: 'match.Match') -> 'match.Match':
        return m.apply_lazy(c.ctx.executor, self.apply_concrete)
