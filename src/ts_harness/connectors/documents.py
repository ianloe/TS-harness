"""Secure PDF and Markdown document upload, extraction, quarantine, and download."""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field
from pypdf import PdfReader

from ts_harness.guardrails.injection import detect_injection_signals, quarantine_untrusted

ALLOWED_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".md", ".markdown"})
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # 10 MiB


class DocumentValidationError(ValueError):
    """Raised when an uploaded or requested document fails validation."""


class DocumentMetadata(BaseModel):
    """Metadata for a stored PDF or Markdown document."""

    name: str
    extension: str
    size_bytes: int
    created_at: datetime
    suspicious: bool = False
    injection_signals: list[str] = Field(default_factory=list)


class ExtractedDocument(BaseModel):
    """Extracted text wrapped in an untrusted-data quarantine block."""

    metadata: DocumentMetadata
    quarantined_text: str


class DocumentStore:
    """Manages PDF and Markdown uploads/downloads inside a confined directory."""

    def __init__(self, root_dir: Path, max_bytes: int = MAX_DOCUMENT_BYTES) -> None:
        self._root = root_dir.resolve()
        self._max_bytes = max_bytes

    @property
    def root_dir(self) -> Path:
        return self._root

    def save_upload(self, filename: str, content: bytes) -> DocumentMetadata:
        """Validate and store an uploaded PDF or Markdown file."""
        safe_name = self._sanitise_filename(filename)
        ext = Path(safe_name).suffix.lower()
        if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
            raise DocumentValidationError(
                f"Unsupported file extension '{ext}'. Allowed: .pdf, .md, .markdown."
            )
        if len(content) == 0:
            raise DocumentValidationError("Uploaded file is empty.")
        if len(content) > self._max_bytes:
            raise DocumentValidationError(
                f"File exceeds maximum size of {self._max_bytes} bytes."
            )

        if ext == ".pdf" and not content.startswith(b"%PDF-"):
            raise DocumentValidationError("Invalid PDF file: missing %PDF- header.")

        self._root.mkdir(parents=True, exist_ok=True)
        target = self._resolve_safe(safe_name)
        target.write_bytes(content)

        extracted = self._extract_raw_text(target, ext)
        scan = detect_injection_signals(extracted)
        return DocumentMetadata(
            name=safe_name,
            extension=ext,
            size_bytes=len(content),
            created_at=datetime.now(UTC),
            suspicious=scan.suspicious,
            injection_signals=scan.matched_signals,
        )

    def list_documents(self) -> list[DocumentMetadata]:
        """List stored PDF and Markdown documents."""
        if not self._root.exists():
            return []
        docs: list[DocumentMetadata] = []
        for path in sorted(self._root.iterdir()):
            if path.is_file() and path.suffix.lower() in ALLOWED_DOCUMENT_EXTENSIONS:
                stat = path.stat()
                docs.append(
                    DocumentMetadata(
                        name=path.name,
                        extension=path.suffix.lower(),
                        size_bytes=stat.st_size,
                        created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    )
                )
        return docs

    def get_download_path(self, filename: str) -> Path:
        """Resolve a stored document path for download, preventing path traversal."""
        safe_name = self._sanitise_filename(filename)
        target = self._resolve_safe(safe_name)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"Document '{safe_name}' not found.")
        return target

    def read_quarantined(self, filename: str) -> ExtractedDocument:
        """Extract text from a PDF or Markdown file and wrap it as untrusted data."""
        target = self.get_download_path(filename)
        ext = target.suffix.lower()
        raw_text = self._extract_raw_text(target, ext)
        scan = detect_injection_signals(raw_text)
        stat = target.stat()
        meta = DocumentMetadata(
            name=target.name,
            extension=ext,
            size_bytes=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            suspicious=scan.suspicious,
            injection_signals=scan.matched_signals,
        )
        return ExtractedDocument(
            metadata=meta,
            quarantined_text=quarantine_untrusted(raw_text, f"document:{target.name}"),
        )

    @staticmethod
    def _sanitise_filename(filename: str) -> str:
        base = Path(filename).name.strip()
        cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)
        if not cleaned or cleaned in {".", ".."}:
            raise DocumentValidationError("Invalid filename.")
        return cleaned

    def _resolve_safe(self, safe_name: str) -> Path:
        target = (self._root / safe_name).resolve()
        if target.parent != self._root:
            raise DocumentValidationError("Path traversal is not permitted.")
        return target

    @staticmethod
    def _extract_raw_text(path: Path, ext: str) -> str:
        if ext in {".md", ".markdown"}:
            return path.read_text(encoding="utf-8", errors="replace")
        reader = PdfReader(io.BytesIO(path.read_bytes()))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages).strip()
