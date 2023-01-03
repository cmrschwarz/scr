import lxml.html
from typing import BinaryIO, Optional, TypeVar, Generic
from abc import ABC, abstractmethod
from concurrent.futures import Future


class Match(ABC):
    parent: Optional['Match'] = None
    args: dict[str, 'Match']

    def __init__(self, parent: Optional['Match']):
        if parent is not None:
            self.parent = parent
        self.args = {}

    def resolve(self) -> 'Match':
        return self


class MatchHTML(Match):
    html: lxml.html.HtmlElement

    def __init__(self, parent: Optional[Match], html: lxml.html.HtmlElement):
        super().__init__(parent)
        self.html = html


class MatchText(Match):
    text: str

    def __init__(self, parent: Optional[Match], text: str):
        super().__init__(parent)
        self.text = text


class MatchData(Match):
    data: bytes

    def __init__(self,  parent: Optional[Match], data: bytes):
        super().__init__(parent)
        self.data = data


class MatchImage(MatchData):
    def __init__(self,  parent: Optional[Match], data: bytes):
        super().__init__(parent, data)
        self.data = data


class MatchDataStream(Match):
    data_stream: BinaryIO

    def __init__(self, data_stream: BinaryIO, parent: Optional['Match'] = None):
        super().__init__(parent)
        self.data_stream = data_stream

    def resolve(self) -> MatchData:
        data = self.data_stream.read()
        return MatchData(self, data)


M = TypeVar("M", bound=Match)


class MatchFuture(Match, Generic[M], ABC):
    def __init__(self, parent: Optional['Match'] = None):
        super().__init__(parent)

    @abstractmethod
    def resolve(self) -> M:
        raise NotImplementedError


class MatchFutureData(MatchFuture[MatchData]):
    future: Future[bytes]

    def __init__(self, future: Future[bytes], parent: Optional['Match'] = None):
        super().__init__(parent)
        self.future = future

    def resolve(self) -> MatchData:
        return MatchData(self, self.future.result())


class MatchFutureText(MatchFuture[MatchText]):
    future: Future[str]

    def __init__(self, future: Future[str], parent: Optional['Match'] = None):
        super().__init__(parent)
        self.future = future

    def resolve(self) -> MatchText:
        return MatchText(self, self.future.result())
