"""Application-specific exceptions."""


class KnowledgeAssistantError(Exception):
    """Base class for errors that can be shown to application users."""


class DocumentNotFoundError(KnowledgeAssistantError):
    """Raised when requested document metadata does not exist."""


class InvalidDocumentError(KnowledgeAssistantError):
    """Raised when a source path cannot be accepted as a document."""


class StorageError(KnowledgeAssistantError):
    """Raised when document metadata or stored files cannot be accessed."""


class DocumentConflictError(KnowledgeAssistantError):
    """Raised when document data conflicts with an existing record."""


class DocumentParsingError(KnowledgeAssistantError):
    """Raised when a supported document cannot be decoded or parsed."""


class UnsupportedDocumentTypeError(DocumentParsingError):
    """Raised when no parser supports the document extension."""


class NoExtractableTextError(DocumentParsingError):
    """Raised when parsing succeeds structurally but yields no usable text."""


class OcrError(KnowledgeAssistantError):
    """Raised when OCR is required but unavailable or inference fails."""


class EmbeddingError(KnowledgeAssistantError):
    """Raised when an embedding model cannot load or returns invalid vectors."""


class VectorStoreError(KnowledgeAssistantError):
    """向量库不可用、Schema 不兼容或向量操作失败。"""


class ProcessingInProgressError(KnowledgeAssistantError):
    """同一文档已有一个处理流程正在执行。"""


class DocumentProcessingError(KnowledgeAssistantError):
    """文档处理遇到未归类的内部错误。"""
