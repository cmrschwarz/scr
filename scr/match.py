import os
from types import TracebackType
import lxml.html
from typing import BinaryIO, Optional, Type, Callable
from abc import ABC, abstractmethod
import concurrent.futures
from concurrent.futures import Future
from scr import chain
from scr.transforms import transform_ref
import tempfile


class Match(ABC):
    parent: Optional['Match'] = None
    args: dict[str, 'Match']

    def __init__(self, parent: Optional['Match']):
        if parent is not None:
            self.parent = parent
        self.args = {}

    @abstractmethod
    def resolved_type(self) -> Type['MatchEager']:
        raise NotImplementedError

    def apply_now(self, fn: Callable[['Match'], 'Match']) -> 'Match':
        return fn(self)

    @abstractmethod
    def apply_eager(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[['MatchConcrete'], 'MatchEager']
    ) -> 'Match':
        raise NotImplementedError

    @abstractmethod
    def apply_lazy(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[['MatchConcrete'], 'MatchEager']
    ) -> 'Match':
        raise NotImplementedError

    @abstractmethod
    def result(self, executor: concurrent.futures.Executor) -> 'MatchEager':
        raise NotImplementedError

    def _add_user_if_stream(self, executor: concurrent.futures.Executor) -> 'Match':
        return self

    def add_stream_user(self, executor: concurrent.futures.Executor) -> None:
        self.apply_now(lambda m: m._add_user_if_stream())


class MatchEager(Match):
    def result(self, executor: concurrent.futures.Executor) -> 'MatchEager':
        return self

    # tighter bound on the return type: now MatchEager
    @abstractmethod
    def apply_eager(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[['MatchConcrete'], 'MatchEager']
    ) -> 'MatchEager':
        raise NotImplementedError


class MatchConcrete(MatchEager):
    def apply_eager(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[['MatchConcrete'], MatchEager]
    ) -> MatchEager:
        return fn(self)

    def apply_lazy(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[['MatchConcrete'], MatchEager]
    ) -> Match:
        return MatchFuture(self, self.resolved_type(), executor.submit(fn, self))

    def resolved_type(self) -> Type['MatchEager']:
        return self.__class__


class MatchNone(MatchConcrete):
    pass


class MatchHtml(MatchConcrete):
    html: lxml.html.HtmlElement

    def __init__(self, parent: Optional[Match], html: lxml.html.HtmlElement):
        super().__init__(parent)
        self.html = html


class MatchText(MatchConcrete):
    text: str

    def __init__(self, parent: Optional[Match], text: str):
        super().__init__(parent)
        self.text = text


class MatchData(MatchConcrete):
    data: bytes

    def __init__(self,  parent: Optional[Match], data: bytes):
        super().__init__(parent)
        self.data = data


class MatchImage(MatchData):
    def __init__(self,  parent: Optional[Match], data: bytes):
        super().__init__(parent, data)
        self.data = data


class MatchDataStream(MatchConcrete):
    user_count: int = 0

    def resolved_type(self) -> Type[MatchEager]:
        return MatchData

    @abstractmethod
    def take_stream(self) -> BinaryIO:
        raise NotImplementedError


DATA_STREAM_BUFFER_SIZE = 8192


class MatchDataStreamFileBacked(MatchDataStream):
    filename: str
    streams: list[BinaryIO] = []

    def __init__(self, parent: Optional['Match'], data_stream: BinaryIO, user_count: int):
        super().__init__(parent)
        # TODO: implement cleanup for this
        # LEAK
        file = tempfile.NamedTemporaryFile("wb", delete=False)
        while True:
            buf = data_stream.read(DATA_STREAM_BUFFER_SIZE)
            file.write(buf)
            if len(buf) < DATA_STREAM_BUFFER_SIZE:
                break
        file.close()
        self.filename = file.name
        self.user_count = user_count

    def _add_user_if_stream(self, executor: concurrent.futures.Executor) -> 'Match':
        self.user_count += 1
        return self

    def take_stream(self) -> BinaryIO:
        assert self.user_count > 0
        self.user_count -= 1
        return open(self.filename, "rb")


class MatchDataStreamUnbacked(MatchDataStream):
    data_stream: BinaryIO

    def __init__(self, parent: Optional['Match'], data_stream: BinaryIO):
        super().__init__(parent)
        self.data_stream = data_stream

    def make_file_backed(self) -> MatchDataStreamFileBacked:
        return MatchDataStreamFileBacked(self, self.data_stream, self.user_count)

    def _add_user_if_stream(self, executor: concurrent.futures.Executor) -> 'Match':
        self.user_count += 1
        if self.user_count > 1:
            return MatchFuture(self, MatchData, executor.submit(self.make_file_backed))
        return self

    def take_stream(self) -> BinaryIO:
        assert self.user_count == 1
        return self.data_stream


class MatchList(MatchEager):
    matches: list[Match]

    def __init__(self, parent: Optional[Match]):
        super().__init__(parent)
        self.matches = []

    def resolved_type(self) -> Type[MatchEager]:
        return MatchList

    def append(self, match: Match) -> None:
        self.matches.append(match)

    def append_flatten(self, match: Match) -> None:
        if isinstance(match, MatchList):
            self.matches.extend(match.matches)
        else:
            self.matches.append(match)

    def extend_flatten(self, matches: list[Match]) -> None:
        for m in matches:
            self.append_flatten(m)

    def apply_now(
        self,
        fn: Callable[['Match'], Match]
    ) -> Match:
        for i in range(0, len(self.matches)):
            self.matches[i] = self.matches[i].apply_now(fn)
        return self

    def apply_eager(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[[MatchConcrete], MatchEager]
    ) -> MatchEager:
        ml = MatchList(self)
        for m in self.matches:
            ml.matches.append(m.apply_eager(executor, fn))
        return ml

    def apply_lazy(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[[MatchConcrete], MatchEager]
    ) -> Match:
        ml = MatchList(self)
        for m in self.matches:
            ml.matches.append(m.apply_lazy(executor, fn))
        return ml


class MatchMultiChainAggregate(MatchEager):
    results: dict['chain.Chain', Match]

    def __init__(self, parent: Optional[Match]):
        super().__init__(parent)
        self.results = {}

    def append(self, cn: 'chain.Chain', match: Match) -> None:
        assert cn not in self.results
        self.results[cn] = match

    def apply_now(
        self,
        fn: Callable[['Match'], Match]
    ) -> Match:
        for k in self.results.keys():
            self.results[k] = self.results[k].apply_now(fn)
        return self

    def apply_eager(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[[MatchConcrete], MatchEager]
    ) -> MatchEager:
        raise ValueError("cannot apply on MatchMultiChainAggregate")

    def apply_lazy(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[[MatchConcrete], MatchEager]
    ) -> Match:
        raise ValueError("cannot apply on MatchMultiChainAggregate")


class MatchControlFlowRedirect(MatchEager):
    target: 'transform_ref.TransformRef'

    def __init__(self, target: 'transform_ref.TransformRef', parent: Optional[Match]):
        super().__init__(parent)
        self.target = target

    def resolved_type(self) -> Type[MatchEager]:
        return MatchControlFlowRedirect

    def apply_eager(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[[MatchConcrete], MatchEager]
    ) -> MatchEager:
        raise ValueError("cannot apply on MatchControlFlowRedirect")

    def apply_lazy(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[[MatchConcrete], MatchEager]
    ) -> Match:
        raise ValueError("cannot apply on MatchControlFlowRedirect")


class MultiMatchBuilder:
    _parent: Match
    _res: Optional[MatchEager] = None

    def __init__(self, parent: Match) -> None:
        self._parent = parent

    def append(self, m: MatchEager) -> None:
        if self._res is None:
            self._res = m
        elif isinstance(self._res, MatchList):
            self._res.matches.append(m)
        else:
            ml = MatchList(self._parent)
            ml.append(self._res)
            ml.append(m)
            self._res = ml

    def append_flatten(self, m: MatchEager) -> None:
        if self._res is None:
            self._res = m
        elif isinstance(self._res, MatchList):
            self._res.append_flatten(m)
        else:
            ml = MatchList(self._parent)
            ml.append(self._res)
            ml.append_flatten(m)
            self._res = ml

    def result(self) -> MatchEager:
        if self._res is None:
            return MatchNone(self._parent)
        return self._res


class MatchFuture(Match, ABC):
    res_type: Type[MatchEager]
    future: Future[MatchEager]

    def __init__(self, parent: Optional['Match'], res_type: Type[MatchEager], future: Future[MatchEager]):
        super().__init__(parent)
        self.res_type = res_type
        self.future = future

    def resolved_type(self) -> Type[MatchEager]:
        return self.res_type

    def apply_eager(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[[MatchConcrete], MatchEager]
    ) -> Match:
        return MatchFutureEager(self, self, fn)

    def apply_lazy(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[[MatchConcrete], MatchEager]
    ) -> Match:
        return MatchFutureFuture(self, self, executor, fn)

    def result(self, executor: concurrent.futures.Executor) -> MatchEager:
        return self.future.result()


class MatchFutureFuture(MatchFuture):
    def __init__(
        self,
        parent: Optional[Match],
        base: MatchFuture,
        executor: concurrent.futures.Executor,
        fn: Callable[[MatchConcrete], MatchEager]
    ):
        super().__init__(parent, base.res_type, base.future)
        self.future = executor.submit(lambda: base.result(executor).apply_eager(executor, fn))

    def result(self, executor: concurrent.futures.Executor) -> MatchEager:
        return self.future.result()


class MatchFutureEager(Match):
    base: Match
    # fn: Callable[[MatchConcrete], MatchEager]
    executor: concurrent.futures.Executor

    def __init__(
        self,
        parent: Optional[Match],
        base: Match,
        fn: Callable[[MatchConcrete], MatchEager]
    ):
        super().__init__(parent)
        self.base = base
        self.fn = fn

    def resolved_type(self) -> Type['MatchEager']:
        return self.base.resolved_type()

    def set_result(self, result: MatchEager) -> None:
        self.res = result

    def apply_eager(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[[MatchConcrete], MatchEager]
    ) -> Match:
        return MatchFutureEager(self, self, fn)

    def apply_lazy(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[[MatchConcrete], MatchEager]
    ) -> Match:
        return MatchFuture(
            self,
            self.resolved_type(),
            executor.submit(lambda: self.base.result(executor).apply_eager(executor, fn))
        )

    def result(self, executor: concurrent.futures.Executor) -> MatchEager:
        return self.base.result(executor).apply_eager(executor, self.fn)
