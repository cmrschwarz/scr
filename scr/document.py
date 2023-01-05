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
    def try_parse(val: str) -> Optional[Type['DocumentSource']]:
        if "url".startswith(val):
            return DocumentSourceUrl
        if "file".startswith(val):
            return DocumentSourceFile
        if "string".startswith(val):
            return DocumentSourceString
        if "stdin".startswith(val):
            return DocumentSourceStdin

    @abstractmethod
    def display_path(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def natural_reference_point(self) -> DocumentReferencePoint:
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


class DocumentSourceFile(DocumentSource):
    path: str

    def __init__(self, path: str) -> None:
        self.path = path

    def display_path(self) -> str:
        return self.path

    def natural_reference_point(self) -> DocumentReferencePoint:
        return self.url_str


class DocumentSourceString(DocumentSource):
    def display_path(self) -> str:
        return "<string>"

    def natural_reference_point(self) -> DocumentReferencePoint:
        return DocumentReferencePointNone()


class DocumentSourceStdin(DocumentSource):
    def display_path(self) -> str:
        return "<stdin>"

    def natural_reference_point(self) -> DocumentReferencePoint:
        return DocumentReferencePointNone()


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
