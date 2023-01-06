from typing import Optional, Type
from scr import chain_spec
from abc import ABC, abstractmethod
import urllib.parse


class DocumentReferencePoint(ABC):
    pass


class DocumentReferencePointUrl(DocumentReferencePoint):
    url: urllib.parse.ParseResult
    url_str: str

    def __init__(self, url_str: str, url: Optional[urllib.parse.ParseResult] = None) -> None:
        self.url_str = url_str
        if url is None:
            self.url = urllib.parse.urlparse(url_str)
        else:
            self.url = url


class DocumentReferencePointFolder(DocumentReferencePoint):
    path: str

    def __init__(self, path: str) -> None:
        self.path = path


class DocumentReferencePointNone(DocumentReferencePoint):
    pass


class DocumentSource(ABC):
    @staticmethod
    def try_parse_type(val: str) -> Optional[Type['DocumentSource']]:
        if "url".startswith(val):
            return DocumentSourceUrl
        if "file".startswith(val):
            return DocumentSourceFile
        if "string".startswith(val):
            return DocumentSourceString
        if "stdin".startswith(val):
            return DocumentSourceStdin
        return None

    @abstractmethod
    def display_path(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def natural_reference_point(self) -> DocumentReferencePoint:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def from_str(val: Optional[str]) -> 'DocumentSource':
        raise NotImplementedError


class DocumentSourceUrl(DocumentSource):
    url_str: str
    url: urllib.parse.ParseResult

    def __init__(self, url_str: str, url: Optional[urllib.parse.ParseResult] = None) -> None:
        self.url_str = url_str
        if url is None:
            self.url = urllib.parse.urlparse(url_str)
        else:
            self.url = url

    def display_path(self) -> str:
        return self.url_str

    def natural_reference_point(self) -> DocumentReferencePoint:
        raise NotImplementedError  # TODO

    @staticmethod
    def from_str(val: Optional[str]) -> 'DocumentSource':
        assert val is not None
        return DocumentSourceUrl(val)


class DocumentSourceFile(DocumentSource):
    path: str

    def __init__(self, path: str) -> None:
        self.path = path

    def display_path(self) -> str:
        return self.path

    def natural_reference_point(self) -> DocumentReferencePoint:
        return DocumentReferencePointFolder(self.path)

    @staticmethod
    def from_str(val: Optional[str]) -> 'DocumentSource':
        assert val is not None
        return DocumentSourceFile(val)


class DocumentSourceString(DocumentSource):
    value: str

    def __init__(self, val: str) -> None:
        self.value = val

    def display_path(self) -> str:
        return "<string>"

    def natural_reference_point(self) -> DocumentReferencePoint:
        return DocumentReferencePointNone()

    @staticmethod
    def from_str(val: Optional[str]) -> 'DocumentSource':
        assert val is not None
        return DocumentSourceString(val)


class DocumentSourceStdin(DocumentSource):
    def display_path(self) -> str:
        return "<stdin>"

    def natural_reference_point(self) -> DocumentReferencePoint:
        return DocumentReferencePointNone()

    @staticmethod
    def from_str(val: Optional[str]) -> 'DocumentSource':
        assert val is None
        return DocumentSourceStdin()


class Document:
    source: DocumentSource
    reference_point: DocumentReferencePoint
    applied_chains: 'chain_spec.ChainSpec'

    def __init__(
        self,
        source: DocumentSource,
        reference_point: DocumentReferencePoint,
        applied_chains: 'chain_spec.ChainSpec'
    ) -> None:
        self.source = source
        self.reference_point = reference_point
        self.applied_chains = applied_chains
