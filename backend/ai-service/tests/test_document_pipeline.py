

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from core.config import config
from rag.models import ParseRequest, DocumentChunk
from rag.document_pipeline import (
    load_text,
    clean_text,
    hash_content,
    split_text,
    build_chunks,
    DocumentIngestionService,
)

config.CHUNK_SIZE = 200
config.CHUNK_OVERLAP = 20


# ===================================================================
# load_text
# ===================================================================

class TestLoadText:
    def test_load_txt(self, tmp_path: Path):
        f = tmp_path / "hello.txt"
        f.write_text("Hello world", encoding="utf-8")
        assert load_text(str(f)) == "Hello world"

    def test_load_md(self, tmp_path: Path):
        f = tmp_path / "readme.md"
        f.write_text("# Title", encoding="utf-8")
        assert load_text(str(f)) == "# Title"

    def test_unsupported_extension(self, tmp_path: Path):
        f = tmp_path / "data.pdf"
        f.write_text("ignored", encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported file type"):
            load_text(str(f))

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_text("C:/nonexistent/file.txt")


# ===================================================================
# clean_text
# ===================================================================

class TestCleanText:
    def test_replace_crlf(self):
        assert clean_text("a\r\nb\r\nc") == "a\nb\nc"

    def test_collapse_spaces_and_tabs(self):
        assert clean_text("a   b\t\tc") == "a b c"

    def test_collapse_excessive_newlines(self):
        assert clean_text("a\n\n\n\nb") == "a\n\nb"

    def test_strip_surrounding_whitespace(self):
        assert clean_text("  \nhello  ") == "hello"

    def test_empty_string(self):
        assert clean_text("") == ""

    def test_all_whitespace(self):
        assert clean_text("   \n\n  ") == ""


# ===================================================================
# hash_content
# ===================================================================

class TestHashContent:
    def test_sha256_hexdigest(self):
        h = hash_content("hello")
        assert h == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_different_inputs_different_hashes(self):
        assert hash_content("a") != hash_content("b")

    def test_empty_string(self):
        h = hash_content("")
        assert h == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


# ===================================================================
# split_text
# ===================================================================

class TestSplitText:
    def test_splits_by_double_newline(self):
        chunks = split_text("aaa\n\nbbb\n\nccc", chunk_size=5, chunk_overlap=2)
        assert "aaa" in chunks
        assert "bbb" in chunks
        assert "ccc" in chunks

    def test_respects_chunk_size(self):
        # build text with \n\n every ~80 chars so splitter has split points
        block = ("word " * 14) + "\n\n"  # ~70 chars per segment
        text = block * 10
        chunks = split_text(text, chunk_size=100, chunk_overlap=10)
        assert len(chunks) >= 3
        for c in chunks:
            assert len(c) <= 100

    def test_returns_empty_for_blank_text(self):
        assert split_text("   \n\n  ") == []

    def test_uses_config_defaults_when_not_provided(self):
        text = ("A" * 250) + "\n\n" + ("B" * 250) + "\n\n" + ("C" * 250)
        chunks = split_text(text)
        assert len(chunks) >= 2


# ===================================================================
# build_chunks
# ===================================================================

class TestBuildChunks:
    def test_builds_document_chunks(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text(
            ("para one " * 50) + "\n\n"
            + ("para two " * 50) + "\n\n"
            + ("para three " * 50),
            encoding="utf-8",
        )

        req = ParseRequest(
            file_path=str(f),
            doc_id=42,
            title="Test Doc",
            doc_type="faq",
            category_id=10,
        )
        chunks = build_chunks(req)

        assert len(chunks) >= 2
        for i, chunk in enumerate(chunks):
            assert isinstance(chunk, DocumentChunk)
            assert chunk.metadata.doc_id == 42
            assert chunk.metadata.source == str(f)
            assert chunk.metadata.title == "Test Doc"
            assert chunk.metadata.doc_type == "faq"
            assert chunk.metadata.category_id == 10
            assert chunk.metadata.chunk_type == "text"
            assert chunk.metadata.content_hash == hash_content(chunk.content)

    def test_uses_filename_as_fallback_title(self, tmp_path: Path):
        f = tmp_path / "untitled.md"
        f.write_text("just one paragraph", encoding="utf-8")
        req = ParseRequest(file_path=str(f), doc_id=1)
        chunks = build_chunks(req)
        assert chunks[0].metadata.title == "untitled.md"

    def test_empty_file_returns_empty_list(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        req = ParseRequest(file_path=str(f), doc_id=1)
        assert build_chunks(req) == []


# ===================================================================
# DocumentIngestionService
# ===================================================================

class FakeVectorStore:
    def __init__(self):
        self.chunks = []

    def upsert_chunks(self, chunks):
        self.chunks.extend(chunks)
        return len(chunks)


class TestDocumentIngestionService:
    def test_ingest_success(self, tmp_path: Path):
        f = tmp_path / "doc.txt"
        f.write_text(
            ("block a " * 50) + "\n\n" + ("block b " * 50),
            encoding="utf-8",
        )

        store = FakeVectorStore()
        svc = DocumentIngestionService(vector_store=store)
        req = ParseRequest(file_path=str(f), doc_id=7)
        result = svc.ingest(req)

        assert result["status"] == "success"
        assert result["doc_id"] == 7
        assert result["chunks_count"] == 2
        assert result["inserted_count"] == 2
        assert len(store.chunks) == 2

    def test_ingest_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_text("   \n\n  ", encoding="utf-8")

        store = FakeVectorStore()
        svc = DocumentIngestionService(vector_store=store)
        req = ParseRequest(file_path=str(f), doc_id=8)
        result = svc.ingest(req)

        assert result == {
            "status": "success",
            "doc_id": 8,
            "chunks_count": 0,
            "inserted_count": 0,
        }

    def test_vector_store_is_passed_through(self):
        mock = MagicMock()
        svc = DocumentIngestionService(vector_store=mock)
        assert svc.vector_store is mock
