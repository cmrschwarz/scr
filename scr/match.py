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
    def result(self) -> 'MatchEager':
        raise NotImplementedError

    def _add_user_if_stream(self, executor: concurrent.futures.Executor) -> 'Match':
        return self

    def add_stream_user(self, executor: concurrent.futures.Executor) -> None:
        self.apply_now(lambda m: m._add_user_if_stream(executor))


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
        return MatchFutureSubmitted(self, self.resolved_type(), executor.submit(fn, self))

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

    def __init__(self, parent: Optional['Match'], filename: str, user_count: int):
        super().__init__(parent)
        self.filename = filename
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
        # TODO: implement cleanup for this
        # LEAK
        file = tempfile.NamedTemporaryFile("wb", delete=False)
        while True:
            buf = self.data_stream.read(DATA_STREAM_BUFFER_SIZE)
            file.write(buf)
            if len(buf) < DATA_STREAM_BUFFER_SIZE:
                break
        file.close()
        return MatchDataStreamFileBacked(self, file.name, self.user_count)

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
    matches: list[tuple['transform_ref.TransformRef', Match]]

    def __init__(self, parent: Optional[Match]):
        super().__init__(parent)
        self.matches = []

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

    def __init__(self, parent: Optional['Match'], res_type: Type[MatchEager]):
        super().__init__(parent)
        self.res_type = res_type

    def resolved_type(self) -> Type[MatchEager]:
        return self.res_type

    def apply_eager(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[[MatchConcrete], MatchEager]
    ) -> Match:
        return MatchEagerOnFuture(self, self, fn)

    def apply_lazy(
        self,
        executor: concurrent.futures.Executor,
        fn: Callable[[MatchConcrete], MatchEager]
    ) -> Match:
        return MatchFutureOnFuture(self, self, executor, fn)

    @abstractmethod
    def add_done_callback(self, cb: Callable[[MatchEager], None]) -> None:
        raise NotImplementedError


class MatchFutureSubmitted(MatchFuture):
    future: Future[MatchEager]

    def __init__(self, parent: Optional['Match'], res_type: Type[MatchEager], future: Future[MatchEager]):
        super().__init__(parent, res_type)
        self.future = future

    def result(self) -> MatchEager:
        return self.future.result()

    def add_done_callback(self, cb: Callable[[MatchEager], None]) -> None:
        self.future.add_done_callback(lambda fut: cb(fut.result()))


class MatchEagerOnFuture(MatchFuture):
    parent: MatchFuture
    res: Optional[MatchEager] = None
    fn: Callable[[MatchConcrete], MatchEager]
    done_callbacks: list[Callable[[MatchEager], None]]

    def __init__(
        self,
        parent: MatchFuture,
        fn: Callable[[MatchConcrete], MatchEager]
    ):
        super().__init__(parent, parent.res_type())
        self.fn = fn
        self.parent.add_done_callback(self.run)

    def run(self, parent_result: MatchEager) -> None:
        self.res = parent_result.apply_eager(self.fn)
        for dc in self.done_callbacks:
            dc(self.res)

    def result(self) -> MatchEager:
        self.parent.result()
        return self.res

    def add_done_callback(self, cb: Callable[[MatchEager], None]) -> None:
        # TODO: think about thread safety here?
        if self.res is None:
            self.done_callbacks.append(cb)
        else:
            cb(self.res)


class MatchFutureOnFuture(MatchFuture):
    parent: MatchFuture
    future: Optional[Future[MatchEager]]
    fn: Callable[[MatchConcrete], MatchEager]
    done_callbacks: list[Callable[[MatchEager], None]]

    def __init__(
        self,
        parent: MatchFuture,
        executor: concurrent.futures.Executor,
        fn: Callable[[MatchConcrete], MatchEager]
    ):
        super().__init__(parent, parent.res_type())
        self.fn = fn
        self.parent.add_done_callback(lambda result: self.run(result, executor))

    def run(self, parent_result: MatchEager, executor: concurrent.futures.Executor) -> None:
        self.future = executor.submit(self.fn, parent_result)
        for dc in self.done_callbacks:
            self.future.add_done_callback(dc)

    def result(self) -> MatchEager:
        self.parent.result()
        assert self.future is not None
        return self.future.result()

    def add_done_callback(self, cb: Callable[[MatchEager], None]) -> None:
        # TODO: think about thread safety here?
        if self.future is None:
            self.done_callbacks.append(cb)
        else:
            self.future.add_done_callback(cb)
