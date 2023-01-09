from abc import ABC, abstractmethod
from scr import chain, chain_options, match, chain_spec, chain_prototype
from typing import Any, Optional, Type


class TransformCreationError(Exception):
    pass


class TransformApplicationError(Exception):
    tf: 'Transform'

    def __init__(self, cn: 'chain.Chain', tf: 'Transform', *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.cn = cn
        self.tf = tf

    def __str__(self) -> str:
        return f"in chain {self.cn}, transform '{self.tf.label}': {super().__str__()}"


class Transform(ABC):
    label: str

    def __init__(self, label: str) -> None:
        self.label = label

    @staticmethod
    @abstractmethod
    def create(label: str, value: Optional[str], current: 'chain_prototype.ChainPrototype', chainspec: 'chain_spec.ChainSpec') -> 'Transform':
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def name_matches(name: str) -> bool:
        raise NotImplementedError

    # should return None if any are accepted e.g. for next or sleep
    @abstractmethod
    def input_match_types(self) -> Optional[set[Type[match.MatchConcrete]]]:
        raise NotImplementedError

    # should return None if the transform does not affect the type of the
    # given match at all, e.g. for next or sleep
    @abstractmethod
    def output_match_types(self) -> Optional[set[Type[match.MatchConcrete]]]:
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
