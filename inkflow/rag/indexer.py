"""Robust RAG indexer using SQLite FTS5 (Full Text Search).

Provides high-performance keyword-based retrieval for chapter consistency.
Uses SQLite's built-in FTS5 virtual tables for efficiency and persistence.
"""

import sqlite3
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class TextChunk:
    """A chunk of text with metadata."""
    def __init__(self, text: str, chapter: int, chunk_id: int, start_pos: int = 0):
        self.text = text
        self.chapter = chapter
        self.chunk_id = chunk_id
        self.start_pos = start_pos

    def to_dict(self) -> dict:
        return {"text": self.text, "chapter": self.chapter, "chunk_id": self.chunk_id, "start_pos": self.start_pos}


def chunk_text(text: str, chunk_size: int = 600, overlap: int = 150) -> List[Tuple[str, int]]:
    """Split text into overlapping chunks."""
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current = ""
    current_start = 0
    pos = 0

    for para in paragraphs:
        if len(current) + len(para) > chunk_size and current:
            chunks.append((current.strip(), current_start))
            overlap_text = current[-overlap:] if len(current) > overlap else current
            current_start = pos - len(overlap_text)
            current = overlap_text + "\n\n" + para
        else:
            if not current: current_start = pos
            current += "\n\n" + para if current else para
        pos += len(para) + 2

    if current.strip():
        chunks.append((current.strip(), current_start))
    return chunks


def _tokenize_chinese(text: str) -> str:
    """Add spaces between Chinese characters to help SQLite FTS5 tokenize them.
    Also handles basic punctuation to keep tokens clean.
    """
    if not text:
        return ""
    # Space out CJK characters
    text = re.sub(r'([\u4e00-\u9fa5])', r' \1 ', text)
    # Collapse multiple spaces
    return " ".join(text.split())


class ChapterIndex:
    """SQLite-backed index for chapter text retrieval."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path
        self._conn = None
        if db_path:
            self._init_db()

    def _get_conn(self):
        if not self._conn:
            if not self.db_path:
                self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            else:
                self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._init_db()
        return self._conn

    def _init_db(self):
        """Create FTS5 table if not exists."""
        if not self._conn:
            return
        # We use a trick: 'searchable' is the tokenized text for MATCH
        # 'original' is the actual text to return
        self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(searchable, original UNINDEXED, chapter UNINDEXED, chunk_id UNINDEXED, start_pos UNINDEXED)")
        self._conn.commit()

    def add_chapter(self, chapter_number: int, text: str):
        """Add a chapter's text to the index."""
        conn = self._get_conn()
        # Delete old chunks for this chapter
        conn.execute("DELETE FROM chunks_fts WHERE chapter = ?", (chapter_number,))

        # Chunk and insert
        for i, (chunk_text_str, start_pos) in enumerate(chunk_text(text)):
            # Tokenize for FTS5
            tokenized_text = _tokenize_chinese(chunk_text_str)
            conn.execute(
                "INSERT INTO chunks_fts(searchable, original, chapter, chunk_id, start_pos) VALUES (?, ?, ?, ?, ?)",
                (tokenized_text, chunk_text_str, chapter_number, i, start_pos)
            )
        conn.commit()

    def remove_chapter(self, chapter_number: int):
        """删除指定章节的索引"""
        conn = self._get_conn()
        conn.execute("DELETE FROM chunks_fts WHERE chapter = ?", (chapter_number,))
        conn.commit()

    def search(self, query: str, max_results: int = 5, exclude_chapter: int = None) -> List[TextChunk]:
        """Search for chunks relevant to the query using FTS5 MATCH."""
        conn = self._get_conn()
        
        # Clean and tokenize query
        clean_query = _tokenize_chinese(query)
        if not clean_query:
            return []

        sql = "SELECT original, chapter, chunk_id, start_pos FROM chunks_fts WHERE chunks_fts MATCH ? "
        params = [clean_query]
        
        if exclude_chapter is not None:
            sql += " AND chapter != ?"
            params.append(exclude_chapter)
            
        sql += " ORDER BY rank LIMIT ?"
        params.append(max_results)

        try:
            cursor = conn.execute(sql, params)
            results = []
            for row in cursor:
                results.append(TextChunk(text=row[0], chapter=row[1], chunk_id=row[2], start_pos=row[3]))
            return results
        except sqlite3.OperationalError:
            # Fallback for empty or complex queries
            return []

    def get_stats(self) -> Dict:
        conn = self._get_conn()
        count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        chapters = conn.execute("SELECT count(distinct chapter) FROM chunks_fts").fetchone()[0]
        return {"total_chunks": count, "chapters_indexed": chapters}

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self):
        self.close()

    def commit(self):
        """Manually commit changes to disk."""
        if self._conn:
            self._conn.commit()

    @staticmethod
    def _resolve_db_path(path: Path) -> Path:
        """Map legacy ``rag_index.json`` paths to ``rag_index.sqlite``.

        Earlier versions persisted the index as JSON. The SQLite FTS5 backend
        cannot reuse that file, so we silently rewrite the suffix and leave
        the stale .json file alone (it will simply be ignored).
        """
        p = Path(path)
        if p.suffix.lower() == ".json":
            return p.with_suffix(".sqlite")
        return p

    def save(self, path: Optional[Path] = None):
        """Persist changes. If a new path is given, snapshot the DB to it.

        Connection state is preserved (no swapping) so callers can keep using
        an in-memory index while still backing up to disk.
        """
        if not self._conn:
            return
        self._conn.commit()

        if path is None:
            return

        target = self._resolve_db_path(path)
        if self.db_path and target == self.db_path:
            return  # already persisted on commit

        target.parent.mkdir(parents=True, exist_ok=True)
        # SQLite's online backup API copies the live DB safely.
        backup_conn = sqlite3.connect(str(target))
        try:
            self._conn.backup(backup_conn)
        finally:
            backup_conn.close()

    def load(self, path: Path):
        """Switch to a different FTS5 database on disk.

        Falls back gracefully when the on-disk file is missing or is the
        legacy JSON format: in that case we keep an empty SQLite DB at the
        resolved path so subsequent writes succeed.
        """
        target = self._resolve_db_path(path)

        if self._conn:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None

        self.db_path = target

        # If a legacy or unreadable file is sitting at target, ignore it.
        # The FTS5 schema is created lazily on next _get_conn() call.
        if target.exists():
            try:
                test_conn = sqlite3.connect(str(target))
                test_conn.execute("SELECT count(*) FROM chunks_fts").fetchone()
                test_conn.close()
            except sqlite3.DatabaseError:
                # Not a valid SQLite file (likely the legacy .json blob saved
                # under a .sqlite name by a buggy build). Replace it.
                try:
                    target.unlink()
                except OSError:
                    pass
