"""Outline API router — CRUD for the rolling outline window."""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from inkflow.memory.outline_window import ChapterOutline
from inkflow.api.deps import get_ws, save_ws

router = APIRouter(prefix="/api/outline", tags=["outline"])


class OutlineUpdate(BaseModel):
    """Partial update for a chapter outline."""
    chapter_goal: Optional[str] = None
    core_conflict: Optional[str] = None
    character_arcs: Optional[list] = None
    key_events: Optional[list] = None
    info_release: Optional[list] = None
    foreshadowing_actions: Optional[dict] = None
    emotional_direction: Optional[str] = None
    notes: Optional[str] = None


@router.get("")
def get_outlines(project_id: str = "default"):
    """Get all outlines in the window."""
    ws = get_ws(project_id)
    outlines = ws.outline_window.get_all()
    return {
        "current_chapter": ws.current_chapter,
        "outlines": [o.to_dict() for o in outlines],
    }


@router.get("/{chapter_number}")
def get_outline(chapter_number: int, project_id: str = "default"):
    """Get outline for a specific chapter."""
    ws = get_ws(project_id)
    o = ws.outline_window.get_outline(chapter_number)
    if not o:
        raise HTTPException(404, f"No outline for chapter {chapter_number}")
    return o.to_dict()


@router.put("/{chapter_number}")
def update_outline(chapter_number: int, body: OutlineUpdate, project_id: str = "default"):
    """Update an outline (e.g., user edits before confirming)."""
    ws = get_ws(project_id)
    o = ws.outline_window.get_outline(chapter_number)
    if not o:
        raise HTTPException(404, f"No outline for chapter {chapter_number}")

    data = body.model_dump(exclude_none=True)
    for key, val in data.items():
        if hasattr(o, key):
            setattr(o, key, val)

    save_ws(project_id, ws)
    return o.to_dict()


@router.post("/{chapter_number}/confirm")
def confirm_outline(chapter_number: int, project_id: str = "default"):
    """Confirm an outline (marks it as confirmed)."""
    ws = get_ws(project_id)
    o = ws.outline_window.get_outline(chapter_number)
    if not o:
        raise HTTPException(404, f"No outline for chapter {chapter_number}")
    o.status = "confirmed"
    save_ws(project_id, ws)
    return {"ok": True, "status": "confirmed"}


@router.post("/{chapter_number}/reject")
def reject_outline(chapter_number: int, project_id: str = "default"):
    """Reject an outline (marks it as rejected)."""
    ws = get_ws(project_id)
    o = ws.outline_window.get_outline(chapter_number)
    if not o:
        raise HTTPException(404, f"No outline for chapter {chapter_number}")
    o.status = "rejected"
    save_ws(project_id, ws)
    return {"ok": True, "status": "rejected"}


@router.post("/generate")
def generate_outlines(project_id: str = "default"):
    """Force regenerate the outline window."""
    ws = get_ws(project_id)
    from inkflow.pipeline.outline_writer import OutlineWriter
    ow = OutlineWriter()

    # Reset and regenerate
    ws.outline_window.outlines.clear()
    if ws.current_chapter == 0:
        ws.outline_window = ow.cold_start(ws)
    else:
        ow.fill_window(ws, ws.outline_window)
    save_ws(project_id, ws)
    outlines = ws.outline_window.get_all()
    return {"ok": True, "outlines": [o.to_dict() for o in outlines]}
