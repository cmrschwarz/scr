from abc import ABC, abstractmethod
from scr import chain, chain_options, chain, match, chain_spec
from typing import Optional


class TransformValueError(Exception):
    pass


class TransformSetupError(Exception):
    cn: 'chain.Chain'
    tf: 'Transform'
    tf_index: int

    def __init__(
        self,
        cn: 'chain.Chain',
        tf: 'Transform',
        tf_index: int,
        *args: object
    ) -> None:
        super().__init__(*args)
        self.cn = cn
        self.tf = tf
        self.tf_index = tf_index


class Transform(ABC):
    label: str

    def __init__(self, label: str) -> None:
        self.label = label

    @staticmethod
    @abstractmethod
    def create(label: str, value: Optional[str], chainspec: 'chain_spec.ChainSpec') -> 'Transform':
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

    def get_next_chain_context(self, current: 'chain_options.ChainOptions') -> 'chain_options.ChainOptions':
        return current

    def setup(self, cn: 'chain.Chain', transform_index: int) -> 'Transform':
        return self


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
