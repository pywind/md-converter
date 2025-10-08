from __future__ import annotations

from functools import lru_cache
from typing import Dict, Type

from .base import Adapter, AdapterResponse, BaseMarkitdownAdapter
from .docx import DOCXAdapter
from .eml import EMLAdapter
from .html import HTMLAdapter
from .pdf import PDFAdapter
from .pptx import PPTXAdapter
from .txt import TXTAdapter
from .xlsx import XLSXAdapter
from ..detection import DocumentType

_ADAPTER_CLASSES: Dict[DocumentType, Type[Adapter]] = {
    DocumentType.DOCX: DOCXAdapter,
    DocumentType.PPTX: PPTXAdapter,
    DocumentType.XLSX: XLSXAdapter,
    DocumentType.PDF: PDFAdapter,
    DocumentType.HTML: HTMLAdapter,
    DocumentType.TXT: TXTAdapter,
    DocumentType.EML: EMLAdapter,
}


@lru_cache(maxsize=len(_ADAPTER_CLASSES))
def get_adapter(document_type: DocumentType) -> Adapter:
    adapter_cls = _ADAPTER_CLASSES.get(document_type)
    if not adapter_cls:
        raise KeyError(f"No adapter registered for {document_type}")
    return adapter_cls()  # type: ignore[return-value]


__all__ = [
    "Adapter",
    "AdapterResponse",
    "BaseMarkitdownAdapter",
    "get_adapter",
]
