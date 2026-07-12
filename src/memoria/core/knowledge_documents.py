"""Knowledge document validation, text extraction and paragraph-first chunking."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
import zipfile

from memoria.core.config import configs


class KnowledgeDocumentError(ValueError):
    """Raised when an uploaded knowledge document cannot be safely processed."""


@dataclass(frozen=True)
class TextSection:
    text: str
    metadata: dict


@dataclass(frozen=True)
class ExtractedDocument:
    sections: list[TextSection]
    page_count: int | None = None

    @property
    def text(self) -> str:
        return "\n\n".join(section.text for section in self.sections if section.text)


_ALLOWED_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}
_UNSUPPORTED_SUFFIXES = {".doc", ".xlsx", ".xls", ".pptx", ".ppt"}


def validate_document_filename(filename: str) -> None:
    suffix = Path(filename or "").suffix.lower()
    if suffix in _UNSUPPORTED_SUFFIXES:
        raise KnowledgeDocumentError(f"不支持 {suffix or '该'} 格式")
    if suffix not in _ALLOWED_SUFFIXES:
        raise KnowledgeDocumentError("仅支持 TXT、Markdown、PDF 和 DOCX")


def validate_document_size(data: bytes) -> None:
    if not data:
        raise KnowledgeDocumentError("文档为空")
    if len(data) > configs.knowledge_upload_max_bytes:
        raise KnowledgeDocumentError("文档超过 10 MB 上传限制")


def extract_document(filename: str, data: bytes) -> ExtractedDocument:
    validate_document_size(data)
    validate_document_filename(filename)
    suffix = Path(filename or "").suffix.lower()

    if suffix in {".txt", ".md"}:
        extracted = _extract_utf8_text(data)
    elif suffix == ".pdf":
        extracted = _extract_pdf(data)
    else:
        extracted = _extract_docx(data)

    text = extracted.text.strip()
    if not text:
        raise KnowledgeDocumentError("文档未提取到可用文本")
    if len(text) > configs.knowledge_extract_max_chars:
        raise KnowledgeDocumentError("文档提取文本超过 1,000,000 字符限制")
    return extracted


def _extract_utf8_text(data: bytes) -> ExtractedDocument:
    if data.startswith((b"%PDF-", b"PK\x03\x04")) or b"\x00" in data[:4096]:
        raise KnowledgeDocumentError("文件内容与文本扩展名不匹配")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KnowledgeDocumentError("TXT/Markdown 必须使用 UTF-8 编码") from exc
    return ExtractedDocument([TextSection(_normalize_text(text), {})])


def _extract_pdf(data: bytes) -> ExtractedDocument:
    if not data.startswith(b"%PDF-"):
        raise KnowledgeDocumentError("文件内容与 PDF 扩展名不匹配")
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise KnowledgeDocumentError("PDF 文件损坏或无法读取") from exc
    if reader.is_encrypted:
        raise KnowledgeDocumentError("不支持加密 PDF")
    if len(reader.pages) > configs.knowledge_pdf_max_pages:
        raise KnowledgeDocumentError("PDF 超过 300 页限制")

    sections = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = _normalize_text(page.extract_text() or "")
        except Exception as exc:
            raise KnowledgeDocumentError(f"PDF 第 {page_number} 页解析失败") from exc
        if text:
            sections.append(TextSection(text, {"page": page_number}))
    if not sections:
        raise KnowledgeDocumentError("PDF 未包含可提取文本，暂不支持 OCR 扫描件")
    return ExtractedDocument(sections, page_count=len(reader.pages))


def _extract_docx(data: bytes) -> ExtractedDocument:
    if not data.startswith(b"PK\x03\x04") or not zipfile.is_zipfile(BytesIO(data)):
        raise KnowledgeDocumentError("文件内容与 DOCX 扩展名不匹配")
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            if "word/document.xml" not in archive.namelist():
                raise KnowledgeDocumentError("文件不是有效的 DOCX 文档")
        from docx import Document

        document = Document(BytesIO(data))
    except KnowledgeDocumentError:
        raise
    except Exception as exc:
        raise KnowledgeDocumentError("DOCX 文件损坏或无法读取") from exc

    sections = []
    for paragraph in document.paragraphs:
        text = _normalize_text(paragraph.text)
        if text:
            sections.append(TextSection(text, {"kind": "paragraph"}))
    for table_index, table in enumerate(document.tables, start=1):
        for row_index, row in enumerate(table.rows, start=1):
            cells = [_normalize_text(cell.text) for cell in row.cells]
            text = " | ".join(cell for cell in cells if cell)
            if text:
                sections.append(
                    TextSection(
                        text,
                        {"kind": "table", "table": table_index, "row": row_index},
                    )
                )
    if not sections:
        raise KnowledgeDocumentError("DOCX 未提取到可用段落或表格文本")
    return ExtractedDocument(sections)


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk_document(
    extracted: ExtractedDocument,
    *,
    target_chars: int | None = None,
    overlap_chars: int | None = None,
) -> list[dict]:
    target = target_chars or configs.knowledge_chunk_chars
    overlap = (
        configs.knowledge_chunk_overlap_chars
        if overlap_chars is None
        else overlap_chars
    )
    overlap = min(max(0, overlap), max(0, target - 1))

    units: list[tuple[str, dict]] = []
    for section in extracted.sections:
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", section.text)
            if paragraph.strip()
        ]
        for paragraph in paragraphs:
            if len(paragraph) <= target:
                units.append((paragraph, section.metadata))
                continue
            start = 0
            while start < len(paragraph):
                end = min(len(paragraph), start + target)
                units.append((paragraph[start:end], section.metadata))
                if end >= len(paragraph):
                    break
                start = max(start + 1, end - overlap)

    chunks: list[dict] = []
    buffer = ""
    metadata_items: list[dict] = []

    def flush() -> None:
        nonlocal buffer, metadata_items
        content = buffer.strip()
        if not content:
            return
        chunks.append(
            {
                "chunk_index": len(chunks),
                "content": content,
                "source_metadata": _merge_metadata(metadata_items),
            }
        )
        buffer = content[-overlap:] if overlap else ""
        metadata_items = metadata_items[-1:] if metadata_items else []

    for text, metadata in units:
        separator = "\n\n" if buffer else ""
        if buffer and len(buffer) + len(separator) + len(text) > target:
            flush()
            separator = "\n\n" if buffer else ""
        buffer = f"{buffer}{separator}{text}"
        metadata_items.append(metadata)
        if len(buffer) >= target:
            flush()
    flush()
    return chunks


def _merge_metadata(items: list[dict]) -> dict:
    pages = sorted({item["page"] for item in items if item.get("page") is not None})
    result = {}
    if pages:
        result["pages"] = pages
    kinds = sorted({item["kind"] for item in items if item.get("kind")})
    if kinds:
        result["kinds"] = kinds
    return result
