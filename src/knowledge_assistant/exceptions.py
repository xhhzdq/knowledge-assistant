"""Application-specific exceptions."""


class KnowledgeAssistantError(Exception):
    """Base class for errors that can be shown to application users."""


class DocumentNotFoundError(KnowledgeAssistantError):
    """Raised when requested document metadata does not exist."""


class InvalidDocumentError(KnowledgeAssistantError):
    """Raised when a source path cannot be accepted as a document."""


class StorageError(KnowledgeAssistantError):
    """Raised when document metadata or stored files cannot be accessed."""
