"""Document-management application service."""

from pathlib import Path
from shutil import copy2
from uuid import uuid4

from knowledge_assistant.exceptions import InvalidDocumentError, StorageError
from knowledge_assistant.models import Document
from knowledge_assistant.repositories.json_repository import JsonDocumentRepository


class DocumentService:
    """Coordinate source files and persisted document metadata."""

    def __init__(self, repository: JsonDocumentRepository, uploads_dir: Path) -> None:
        self._repository = repository
        self._uploads_dir = uploads_dir.resolve()

    def add_document(self, source: Path) -> Document:
        """Validate and copy a source file, then persist its metadata."""
        source = source.expanduser().resolve()
        if not source.exists():
            raise InvalidDocumentError(f"Source file does not exist: {source}")
        if not source.is_file():
            raise InvalidDocumentError(f"Source path is not a file: {source}")

        self._uploads_dir.mkdir(parents=True, exist_ok=True)
        destination = self._uploads_dir / f"{uuid4().hex}_{source.name}"
        document = Document.create(
            original_path=str(source),
            stored_path=str(destination),
            file_size=source.stat().st_size,
        )

        try:
            copy2(source, destination)
            self._repository.add(document)
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise StorageError(f"Unable to copy document: {source}") from exc
        except StorageError:
            destination.unlink(missing_ok=True)
            raise

        return document

    def list_documents(self) -> list[Document]:
        """Return all managed documents."""
        return self._repository.list_all()

    def get_document(self, document_id: str) -> Document:
        """Return one managed document."""
        return self._repository.get_by_id(document_id)

    def delete_document(self, document_id: str) -> Document:
        """Delete a stored file and its metadata."""
        document = self._repository.get_by_id(document_id)
        stored_file = Path(document.stored_path).resolve()

        try:
            stored_file.relative_to(self._uploads_dir)
        except ValueError as exc:
            raise StorageError("Refusing to delete a file outside the uploads directory") from exc

        try:
            stored_file.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(f"Unable to delete stored file: {stored_file}") from exc

        return self._repository.delete(document_id)
