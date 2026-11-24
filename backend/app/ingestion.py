from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pytesseract
from PIL import Image

from .knowledge_domain import excerpt, normalize_tags

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".md",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_PDF_PAGES = 300
MAX_IMAGE_PIXELS = 40_000_000

IMAGE_FORMATS = {
    ".png": ("PNG", "image/png"),
    ".jpg": ("JPEG", "image/jpeg"),
    ".jpeg": ("JPEG", "image/jpeg"),
    ".webp": ("WEBP", "image/webp"),
}

CANONICAL_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".md": "text/markdown",
    ".txt": "text/plain",
    **{suffix: mime for suffix, (_format, mime) in IMAGE_FORMATS.items()},
}


@dataclass(frozen=True)
class TextExtraction:
    text: str
    status: str
    error: str | None = None


@dataclass(frozen=True)
class KnowledgeChunkDraft:
    title: str
    excerpt: str
    search_text: str
    tags: list[str]


def validate_upload(filename: str, size: int) -> str:
    suffix = Path(filename).suffix.casefold()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("unsupported_file_type")
    if size <= 0:
        raise ValueError("empty_file")
    if size > MAX_UPLOAD_BYTES:
        raise ValueError("file_too_large")
    return suffix


def inspect_uploaded_file(path: Path, suffix: str) -> str:
    if suffix in IMAGE_FORMATS:
        expected_format, canonical_mime = IMAGE_FORMATS[suffix]
        try:
            with Image.open(path) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("invalid_file_content")
                if image.format != expected_format:
                    raise ValueError("invalid_file_content")
                image.verify()
        except (OSError, ValueError):
            raise ValueError("invalid_file_content") from None
        return canonical_mime

    if suffix == ".pdf":
        if path.read_bytes()[:5] != b"%PDF-":
            raise ValueError("invalid_file_content")
        return CANONICAL_MIME_TYPES[suffix]

    if suffix in {".docx", ".pptx"}:
        try:
            with ZipFile(path) as archive:
                names = set(archive.namelist())
                total_size = sum(item.file_size for item in archive.infolist())
                expected_prefix = "word/" if suffix == ".docx" else "ppt/"
                if (
                    "[Content_Types].xml" not in names
                    or not any(name.startswith(expected_prefix) for name in names)
                    or total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES
                ):
                    raise ValueError("invalid_file_content")
        except (BadZipFile, OSError):
            raise ValueError("invalid_file_content") from None
        return CANONICAL_MIME_TYPES[suffix]

    if suffix in {".md", ".txt"}:
        _decode_text_file(path)
        return CANONICAL_MIME_TYPES[suffix]

    raise ValueError("unsupported_file_type")


def _decode_text_file(path: Path) -> str:
    payload = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("unsupported_text_encoding")


def _strip_markdown_metadata(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            end = next(
                index
                for index, line in enumerate(lines[1:], start=1)
                if line.strip() == "---"
            )
        except StopIteration:
            pass
        else:
            return "\n".join(lines[end + 1 :]).lstrip("\n")

    known_keys = {
        "title",
        "module",
        "knowledge_point",
        "tags",
        "course",
    }
    index = 0
    while index < len(lines):
        match = re.match(r"^([A-Za-z_][\w-]*):\s*.+$", lines[index])
        if not match or match.group(1) not in known_keys:
            break
        index += 1
    if index < 2:
        return text
    if index < len(lines) and not lines[index].strip():
        index += 1
    return "\n".join(lines[index:])


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError("document_too_complex")
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)


def _extract_docx(path: Path) -> str:
    from docx import Document

    document = Document(str(path))
    parts = [paragraph.text.strip() for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n\n".join(part for part in parts if part)


def _extract_pptx(path: Path) -> str:
    from pptx import Presentation

    presentation = Presentation(str(path))
    slides: list[str] = []
    for index, slide in enumerate(presentation.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                value = shape.text.strip()
                if value:
                    parts.append(value)
        if parts:
            slides.append(f"# 第 {index} 页\n\n" + "\n\n".join(parts))
    return "\n\n".join(slides)


def _ocr_image(path: Path) -> str:
    with Image.open(path) as image:
        return pytesseract.image_to_string(image, lang="chi_sim+eng").strip()


def extract_text(path: Path, mime_type: str | None) -> TextExtraction:
    suffix = path.suffix.casefold()
    if suffix in {".md", ".txt"}:
        text = _decode_text_file(path)
        if suffix == ".md":
            text = _strip_markdown_metadata(text)
        return TextExtraction(text=text, status="ready")
    if suffix == ".pdf":
        return TextExtraction(text=_extract_pdf(path), status="ready")
    if suffix == ".docx":
        return TextExtraction(text=_extract_docx(path), status="ready")
    if suffix == ".pptx":
        return TextExtraction(text=_extract_pptx(path), status="ready")
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        try:
            text = _ocr_image(path)
        except Exception as exc:
            return TextExtraction(
                text="",
                status="ready_image_only",
                error=f"ocr_unavailable: {exc}",
            )
        if not text:
            return TextExtraction(
                text="",
                status="ready_image_only",
                error="ocr_empty",
            )
        return TextExtraction(text=text, status="ready")
    raise ValueError("unsupported_file_type")


def _paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    parts = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
    result: list[str] = []
    for part in parts:
        while len(part) > 700:
            result.append(part[:700])
            part = part[700:]
        if part:
            result.append(part)
    return result


def _heading_tags(text: str) -> list[str]:
    headings = re.findall(r"(?m)^#{1,6}\s+(.+?)\s*$", text)
    values: list[str] = []
    for heading in headings:
        for item in re.split(r"[\s/|:：,，。；;]+", heading):
            value = item.strip()
            if 2 <= len(value) <= 20:
                values.append(value)
    return normalize_tags(values)


def build_knowledge(
    text: str,
    title: str,
    tags: list[str],
) -> list[KnowledgeChunkDraft]:
    paragraphs = _paragraphs(text)
    if not paragraphs:
        return []

    normalized_title = title.strip() or "未命名知识点"
    all_tags = normalize_tags([*tags, *_heading_tags(text)])
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= 700:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = paragraph
    if current:
        chunks.append(current)

    drafts: list[KnowledgeChunkDraft] = []
    headings = re.findall(r"(?m)^#{1,6}\s+(.+?)\s*$", text)
    for index, chunk in enumerate(chunks[:60], start=1):
        heading = headings[index - 1].strip() if index <= len(headings) else ""
        chunk_title = heading or f"{normalized_title} · {index:02d}"
        chunk_excerpt = excerpt(chunk, 280)
        drafts.append(
            KnowledgeChunkDraft(
                title=chunk_title[:80],
                excerpt=chunk_excerpt,
                search_text=f"{chunk_title}\n{chunk}\n{' '.join(all_tags)}",
                tags=all_tags,
            )
        )
    return drafts
