from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import List

from langchain_text_splitters import CharacterTextSplitter

from core.config import config
from rag.models import ChunkMetadata, DocumentChunk, ParseRequest


def load_text(file_path: str) -> str:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()
    if ext not in {".txt", ".md"}:
        raise ValueError(f"Unsupported file type in first pass: {ext}")

    return path.read_text(encoding="utf-8")


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def split_text(text: str, chunk_size: int | None = None, chunk_overlap: int | None = None) -> List[str]:
    chunk_size = chunk_size or config.CHUNK_SIZE
    chunk_overlap = chunk_overlap or config.CHUNK_OVERLAP

    text = clean_text(text)
    if not text:
        return []

    text_splitter = CharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separator="\n\n",
    )
    return text_splitter.split_text(text)


def build_chunks(request: ParseRequest) -> List[DocumentChunk]:
    raw_text = load_text(request.file_path)
    parts = split_text(raw_text)
    total = len(parts)

    chunks: List[DocumentChunk] = []
    for index, content in enumerate(parts):
        chunks.append(
            DocumentChunk(
                content=content,
                metadata=ChunkMetadata(
                    doc_id=request.doc_id,
                    source=request.file_path,
                    title=request.title or os.path.basename(request.file_path),
                    doc_type=request.doc_type,
                    chunk_type="text",
                    category_id=request.category_id,
                    chunk_index=index,
                    total_chunks=total,
                    content_hash=hash_content(content),
                ),
            )
        )
    return chunks


class DocumentIngestionService:
    def __init__(self, vector_store):
        self.vector_store = vector_store

    def ingest(self, request: ParseRequest) -> dict:
        chunks = build_chunks(request)
        inserted = self.vector_store.upsert_chunks(chunks)
        return {
            "status": "success",
            "doc_id": request.doc_id,
            "chunks_count": len(chunks),
            "inserted_count": inserted,
        }
