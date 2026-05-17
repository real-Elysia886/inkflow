"""Projects API router - Multi-project management."""

from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict

from inkflow.api.deps import _pm as _mgr

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=50)
    name: str = ""
    description: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


@router.get("")
def list_projects():
    return _mgr.list_projects()


@router.post("")
def create_project(body: ProjectCreate):
    try:
        p = _mgr.create_project(body.project_id, body.name, body.description)
        return {"ok": True, "project_id": p.project_id, "name": p.name}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{project_id}")
def get_project(project_id: str):
    try:
        p = _mgr.get_project(project_id)
        return {
            "project_id": p.project_id,
            "name": p.name,
            "description": p.description,
            "created_at": p.created_at,
            "chapter_count": len(p.chapters),
            "world_state": p.world_state.to_dict(),
        }
    except FileNotFoundError:
        raise HTTPException(404, f"Project '{project_id}' not found")


@router.put("/{project_id}")
def update_project(project_id: str, body: ProjectUpdate):
    try:
        p = _mgr.get_project(project_id)
        if body.name is not None:
            p.name = body.name
        if body.description is not None:
            p.description = body.description
        p.save()
        return {"ok": True}
    except FileNotFoundError:
        raise HTTPException(404, f"Project '{project_id}' not found")


@router.put("/{project_id}/skill-map")
def update_skill_map(project_id: str, body: Dict[str, str]):
    """Update the skill map for a project (role_type -> slug)."""
    try:
        p = _mgr.get_project(project_id)
        p.skill_map = body
        p.save()
        return {"ok": True, "skill_map": p.skill_map}
    except FileNotFoundError:
        raise HTTPException(404, f"Project '{project_id}' not found")


@router.get("/{project_id}/skill-map")
def get_skill_map(project_id: str):
    """Get the skill map for a project."""
    try:
        p = _mgr.get_project(project_id)
        return {"skill_map": p.skill_map}
    except FileNotFoundError:
        raise HTTPException(404, f"Project '{project_id}' not found")


@router.delete("/{project_id}")
def delete_project(project_id: str):
    try:
        _mgr.delete_project(project_id)
        # Evict RAG index from memory
        idx = _rag_indices.pop(project_id, None)
        if idx:
            idx.close()
        return {"ok": True}
    except FileNotFoundError:
        raise HTTPException(404, f"Project '{project_id}' not found")


# --- Chapters ---

class ChapterTextUpdate(BaseModel):
    text: str


class FeedbackCreate(BaseModel):
    chapter_number: int
    rating: int = Field(..., ge=1, le=5)
    comment: str = ""
    annotations: list = []


@router.get("/{project_id}/chapters")
def list_chapters(project_id: str):
    try:
        p = _mgr.get_project(project_id)
        return [{
            "chapter_number": ch.get("chapter_number"),
            "title": ch.get("outline", {}).get("chapter_title", ""),
            "word_count": len(ch.get("final_text", "")),
            "passed": ch.get("passed", False),
            "rating": _get_rating(p, ch.get("chapter_number", 0)),
            "edited_by_human": ch.get("edited_by_human", False),
            "saved_at": ch.get("saved_at", ""),
        } for ch in p.chapters]
    except FileNotFoundError:
        raise HTTPException(404, f"Project '{project_id}' not found")


@router.get("/{project_id}/chapters/{chapter_number}")
def get_chapter(project_id: str, chapter_number: int):
    try:
        p = _mgr.get_project(project_id)
        ch = p.get_chapter(chapter_number)
        if not ch:
            raise HTTPException(404, f"Chapter {chapter_number} not found")
        return ch
    except FileNotFoundError:
        raise HTTPException(404, f"Project '{project_id}' not found")


@router.put("/{project_id}/chapters/{chapter_number}")
def update_chapter_text(project_id: str, chapter_number: int, body: ChapterTextUpdate):
    try:
        p = _mgr.get_project(project_id)
        ch = p.get_chapter(chapter_number)
        if not ch:
            raise HTTPException(404, f"Chapter {chapter_number} not found")
        p.update_chapter_text(chapter_number, body.text)
        # Re-index for RAG
        _reindex_chapter(project_id, chapter_number, body.text)
        return {"ok": True}
    except FileNotFoundError:
        raise HTTPException(404, f"Project '{project_id}' not found")


@router.delete("/{project_id}/chapters/{chapter_number}")
def delete_chapter(project_id: str, chapter_number: int):
    try:
        p = _mgr.get_project(project_id)
        ch = p.get_chapter(chapter_number)
        if not ch:
            raise HTTPException(404, f"Chapter {chapter_number} not found")

        # 删除章节
        p.delete_chapter(chapter_number)

        # 删除 RAG 索引
        idx = _get_rag_index(project_id)
        idx.remove_chapter(chapter_number)
        idx.commit()

        return {"ok": True}
    except FileNotFoundError:
        raise HTTPException(404, f"Project '{project_id}' not found")


class ChapterRewriteRequest(BaseModel):
    reason: str = ""  # Optional reason for rewrite


@router.post("/{project_id}/chapters/{chapter_number}/rewrite")
async def rewrite_chapter(project_id: str, chapter_number: int, body: ChapterRewriteRequest):
    """Rewrite a saved chapter based on optional feedback."""
    try:
        p = _mgr.get_project(project_id)
        ch = p.get_chapter(chapter_number)
        if not ch:
            raise HTTPException(404, f"Chapter {chapter_number} not found")

        ws = p.world_state
        current_text = ch.get("final_text", "")
        if not current_text:
            raise HTTPException(400, "Chapter has no text to rewrite")

        from inkflow.utils.llm_utils import call_llm
        from inkflow.pipeline.anti_ai import build_anti_ai_prompt_section, cleanup_dashes, check_dash_count
        from inkflow.pipeline.quality import QualityScorer

        chars = "\n".join(
            f"- {name}: {c.description} ({c.traits})"
            for name, c in ws.characters.items()
        )

        rewrite_prompt = f"""请重写以下章节。

## 世界观
{ws.world_setting or '（未设定）'}

## 角色
{chars or '（无角色）'}

{build_anti_ai_prompt_section()}

## 用户反馈
{body.reason or '（无特定反馈，请优化质量）'}

## 原文
{current_text}

请输出完整的重写后的章节正文。保留章节标题，优化文字质量。"""

        new_text = call_llm(rewrite_prompt, role_name="writer", temperature=0.7,
                           max_tokens=8192, json_mode=False)

        # Clean up dashes
        if check_dash_count(new_text) > 2:
            new_text = cleanup_dashes(new_text, max_dashes=2)

        # Evaluate
        quality = QualityScorer()
        evaluation = quality.evaluate(new_text, "", ws)

        # Return the rewritten version (don't save yet - let user compare)
        return {
            "ok": True,
            "chapter_number": chapter_number,
            "original_text": current_text,
            "rewritten_text": new_text,
            "evaluation": evaluation,
            "original_word_count": len(current_text),
            "rewritten_word_count": len(new_text),
        }

    except FileNotFoundError:
        raise HTTPException(404, f"Project '{project_id}' not found")
    except Exception as e:
        raise HTTPException(500, f"Rewrite failed: {e}")


@router.post("/{project_id}/chapters/{chapter_number}/apply-rewrite")
async def apply_rewrite(project_id: str, chapter_number: int, body: dict):
    """Apply a rewritten chapter (replace the original)."""
    try:
        p = _mgr.get_project(project_id)
        ch = p.get_chapter(chapter_number)
        if not ch:
            raise HTTPException(404, f"Chapter {chapter_number} not found")

        new_text = body.get("text", "")
        if not new_text:
            raise HTTPException(400, "No text provided")

        # Update the chapter
        p.update_chapter_text(chapter_number, new_text)

        # Re-index for RAG
        _reindex_chapter(project_id, chapter_number, new_text)

        return {"ok": True}

    except FileNotFoundError:
        raise HTTPException(404, f"Project '{project_id}' not found")


@router.get("/{project_id}/feedback")
def list_feedback(project_id: str):
    try:
        p = _mgr.get_project(project_id)
        return p.feedback
    except FileNotFoundError:
        raise HTTPException(404, f"Project '{project_id}' not found")


@router.post("/{project_id}/feedback")
def add_feedback(project_id: str, body: FeedbackCreate):
    try:
        p = _mgr.get_project(project_id)
        p.add_feedback(body.chapter_number, body.rating, body.comment, body.annotations)
        return {"ok": True}
    except FileNotFoundError:
        raise HTTPException(404, f"Project '{project_id}' not found")


@router.get("/{project_id}/rag/stats")
def rag_stats(project_id: str):
    from inkflow.rag.indexer import ChapterIndex
    idx = _get_rag_index(project_id)
    return idx.get_stats()


@router.post("/{project_id}/rag/search")
def rag_search(project_id: str, query: str, max_results: int = 5):
    idx = _get_rag_index(project_id)
    results = idx.search(query, max_results=max_results)
    return [{"text": c.text, "chapter": c.chapter, "chunk_id": c.chunk_id} for c in results]


# --- Helpers ---

_rag_indices = {}


def _rag_index_path(project_id: str) -> Path:
    """Return the on-disk SQLite path for the project's RAG index."""
    return _mgr.get_project(project_id).dir / "rag_index.sqlite"


def _get_rag_index(project_id: str):
    from inkflow.rag.indexer import ChapterIndex
    if project_id not in _rag_indices:
        db_path = _rag_index_path(project_id)
        # Migrate: ignore the obsolete rag_index.json silently.
        idx = ChapterIndex(db_path=db_path)
        _rag_indices[project_id] = idx
    return _rag_indices[project_id]


def _reindex_chapter(project_id: str, chapter_number: int, text: str):
    idx = _get_rag_index(project_id)
    idx.add_chapter(chapter_number, text)
    idx.commit()


def _get_rating(p, chapter_number: int) -> int:
    for fb in reversed(p.feedback):
        if fb.get("chapter_number") == chapter_number:
            return fb.get("rating", 0)
    return 0
