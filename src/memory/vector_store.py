"""ChromaDB-backed vector store for course knowledge.

課程向量知識庫 — 儲存課綱、講義、文獻的語義嵌入，支援脈絡感知檢索。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from src.config import settings
from src.models import DocumentChunk


class VectorStore:
    """ChromaDB wrapper for semantic search over course materials."""

    def __init__(self, persist_dir: Optional[Path] = None):
        self.persist_dir = persist_dir or settings.chroma_path
        self._client: Optional[chromadb.ClientAPI] = None

    def initialize(self) -> None:
        """Initialize the ChromaDB client with persistent storage."""
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def _get_collection(self, course_id: str) -> chromadb.Collection:
        """Get or create a collection for a specific course."""
        return self._client.get_or_create_collection(
            name=f"course_{course_id.lower().replace(' ', '_')}",
            metadata={"course_id": course_id},
        )

    def add_chunks(self, course_id: str, chunks: list[DocumentChunk]) -> None:
        """Add document chunks to the course collection."""
        collection = self._get_collection(course_id)
        collection.add(
            ids=[c.id for c in chunks],
            documents=[c.content for c in chunks],
            metadatas=[
                {
                    "source_file": c.source_file,
                    "page_number": c.page_number or -1,
                    "chunk_index": c.chunk_index,
                    **c.metadata,
                }
                for c in chunks
            ],
        )

    def query(
        self,
        course_id: str,
        query_text: str,
        n_results: int = 5,
    ) -> list[dict]:
        """Semantic search within a course's knowledge base."""
        collection = self._get_collection(course_id)
        results = collection.query(
            query_texts=[query_text],
            n_results=n_results,
        )
        output = []
        for i in range(len(results["ids"][0])):
            output.append({
                "id": results["ids"][0][i],
                "content": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i] if results.get("distances") else None,
            })
        return output

    def delete_course(self, course_id: str) -> None:
        """Delete all data for a course."""
        collection_name = f"course_{course_id.lower().replace(' ', '_')}"
        try:
            self._client.delete_collection(collection_name)
        except Exception:
            pass
