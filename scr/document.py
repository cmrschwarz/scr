from enum import Enum
from typing import Optional


class DocumentType(Enum):
    URL = 0
    FILE = 1
    STRING = 3
    STDIN = 4

    @staticmethod
    def try_parse(val: str) -> Optional['DocumentType']:
        for dt in DocumentType:
            if dt.name.lower().startswith(val):
                return dt
        return None


class Document:
    document_type: DocumentType

    pass
