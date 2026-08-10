"""Command-line entry point for the Knowledge Assistant."""

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from knowledge_assistant.core.config import Settings
from knowledge_assistant.exceptions import KnowledgeAssistantError
from knowledge_assistant.models import Document
from knowledge_assistant.repositories.json_repository import JsonDocumentRepository
from knowledge_assistant.services.document_service import DocumentService


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="knowledge-assistant",
        description="Manage documents in the Knowledge Assistant learning project.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Copy a document into managed storage.")
    add_parser.add_argument("source", type=Path, help="Path to the source file.")

    subparsers.add_parser("list", help="List managed documents.")

    show_parser = subparsers.add_parser("show", help="Show document metadata.")
    show_parser.add_argument("document_id", help="Document ID to display.")

    delete_parser = subparsers.add_parser("delete", help="Delete a managed document.")
    delete_parser.add_argument("document_id", help="Document ID to delete.")

    return parser


def build_service() -> DocumentService:
    """Build the local document service from default project settings."""
    settings = Settings.default()
    settings.ensure_data_directories()
    repository = JsonDocumentRepository(settings.metadata_file)
    return DocumentService(repository, settings.uploads_dir)


def print_document(document: Document) -> None:
    """Print one document in a readable form."""
    print(f"ID: {document.id}")
    print(f"Name: {document.name}")
    print(f"Type: {document.file_type or '(none)'}")
    print(f"Size: {document.file_size} bytes")
    print(f"Status: {document.status}")
    print(f"Original path: {document.original_path}")
    print(f"Stored path: {document.stored_path}")
    print(f"Created at: {document.created_at}")


def exit_with_error(parser: argparse.ArgumentParser, message: str) -> NoReturn:
    """Exit through argparse so command-line users receive a concise error."""
    parser.exit(status=1, message=f"Error: {message}\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line application."""
    parser = build_parser()
    args = parser.parse_args(argv)
    service = build_service()

    try:
        if args.command == "add":
            document = service.add_document(args.source)
            print(f"Document added: {document.id}")
        elif args.command == "list":
            documents = service.list_documents()
            if not documents:
                print("No documents found.")
            for document in documents:
                print(f"{document.id}  {document.name}  {document.status}")
        elif args.command == "show":
            print_document(service.get_document(args.document_id))
        elif args.command == "delete":
            document = service.delete_document(args.document_id)
            print(f"Document deleted: {document.id}")
    except KnowledgeAssistantError as exc:
        exit_with_error(parser, str(exc))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
