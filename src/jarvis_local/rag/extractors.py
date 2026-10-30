from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from .models import ChunkDraft, ExtractedSection


SUPPORTED_EXTENSIONS = frozenset({".txt", ".md", ".pdf"})
_SUSPICIOUS_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"ignora\s+(todas\s+)?las\s+instrucciones\s+anteriores",
        r"system\s+prompt",
        r"mensaje\s+del\s+sistema",
        r"<tool_call>",
        r"concede\s+permisos",
    )
)


def extract_sections(path: Path, *, max_bytes: int) -> list[ExtractedSection]:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"El documento excede el límite de {max_bytes} bytes.")
    extension = path.suffix.casefold()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Tipo documental no soportado: {extension}")
    if extension == ".pdf":
        return _extract_pdf(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return _extract_markdown(text) if extension == ".md" else [ExtractedSection(text=text)]


def _extract_pdf(path: Path) -> list[ExtractedSection]:
    reader = PdfReader(path, strict=False)
    if reader.is_encrypted:
        raise ValueError("No se indexan PDF cifrados sin una credencial explícita.")
    sections: list[ExtractedSection] = []
    for index, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            sections.append(ExtractedSection(page_number=index, text=text))
    return sections


def _extract_markdown(text: str) -> list[ExtractedSection]:
    sections: list[ExtractedSection] = []
    title: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            body = "\n".join(buffer).strip()
            if body:
                sections.append(ExtractedSection(title=title, text=body))
            title = match.group(1).strip()
            buffer = []
        else:
            buffer.append(line)
    body = "\n".join(buffer).strip()
    if body or title:
        sections.append(ExtractedSection(title=title, text=body))
    return sections or [ExtractedSection(text=text)]


def chunk_sections(
    sections: list[ExtractedSection], *, max_chars: int, overlap_chars: int
) -> list[ChunkDraft]:
    if overlap_chars >= max_chars:
        raise ValueError("El solapamiento debe ser menor que el tamaño del fragmento.")
    chunks: list[ChunkDraft] = []
    for section in sections:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", section.text) if part.strip()]
        current = ""
        for paragraph in paragraphs:
            pieces = _split_long(paragraph, max_chars)
            for piece in pieces:
                candidate = piece if not current else f"{current}\n\n{piece}"
                if len(candidate) <= max_chars:
                    current = candidate
                    continue
                _append_chunk(chunks, section, current)
                overlap = current[-overlap_chars:].lstrip() if overlap_chars else ""
                current = f"{overlap}\n\n{piece}".strip() if overlap else piece
                if len(current) > max_chars:
                    _append_chunk(chunks, section, current[:max_chars])
                    current = current[max_chars - overlap_chars :].strip()
        if current.strip():
            _append_chunk(chunks, section, current)
    return [chunk.model_copy(update={"index": index}) for index, chunk in enumerate(chunks)]


def _split_long(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        boundary = remaining.rfind(". ", 0, max_chars)
        if boundary < max_chars // 2:
            boundary = remaining.rfind(" ", 0, max_chars)
        if boundary < max_chars // 2:
            boundary = max_chars
        pieces.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _append_chunk(
    chunks: list[ChunkDraft], section: ExtractedSection, content: str
) -> None:
    normalized = content.strip()
    if not normalized:
        return
    chunks.append(
        ChunkDraft(
            index=len(chunks),
            section_title=section.title,
            page_number=section.page_number,
            content=normalized,
            suspicious_instructions=any(
                pattern.search(normalized) for pattern in _SUSPICIOUS_PATTERNS
            ),
        )
    )

