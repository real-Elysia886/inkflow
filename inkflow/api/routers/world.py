"""WorldState management API router."""

import threading
from pathlib import Path
from typing import Literal, Dict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from inkflow.api.schemas.world import (
    CharacterCreate, ForeshadowingCreate, ChapterSummaryCreate,
    WorldStateUpdate, WorldStateSaveRequest,
)
from inkflow.memory.world_state import WorldState
from inkflow.api.deps import get_ws, save_ws

router = APIRouter(prefix="/api/world", tags=["world"])

# Per-project locking for concurrent safety
_project_locks: Dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()

# Allowed directory for load/save (project root/data/)
DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"


def _get_project_lock(project_id: str) -> threading.Lock:
    """Get or create a lock for a specific project."""
    with _locks_lock:
        if project_id not in _project_locks:
            _project_locks[project_id] = threading.Lock()
        return _project_locks[project_id]


def _validate_path(file_path: str) -> Path:
    """Validate that a file path stays within the allowed data directory."""
    p = Path(file_path).resolve()
    if not p.is_relative_to(DATA_DIR.resolve()):
        raise HTTPException(400, f"Path must be inside {DATA_DIR}")
    return p


@router.get("")
def get_world_state(project_id: str = "default"):
    ws = get_ws(project_id)
    return ws.to_dict()


@router.put("")
def update_world_state(body: WorldStateUpdate, project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        if body.world_setting is not None:
            ws.world_setting = body.world_setting
        if body.current_chapter is not None:
            ws.current_chapter = body.current_chapter
        if body.setting_templates is not None:
            ws.setting_templates.update(body.setting_templates)
        save_ws(project_id, ws)
    return {"ok": True}


class GovernanceUpdate(BaseModel):
    author_intent: str = None
    current_focus: str = None


@router.put("/governance")
def update_governance(body: GovernanceUpdate, project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        if body.author_intent is not None:
            ws.author_intent = body.author_intent
        if body.current_focus is not None:
            ws.current_focus = body.current_focus
        save_ws(project_id, ws)
    return {"ok": True}


@router.post("/load")
def load_world_state(file_path: str, project_id: str = "default"):
    p = _validate_path(file_path)
    lock = _get_project_lock(project_id)
    with lock:
        from inkflow.api.deps import _pm
        proj = _pm.get_project(project_id)
        try:
            proj.world_state.load(str(p))
            proj.save()
            return {"ok": True, "current_chapter": proj.world_state.current_chapter}
        except FileNotFoundError:
            raise HTTPException(404, f"File not found: {file_path}")
        except Exception as e:
            raise HTTPException(400, str(e))


@router.post("/save")
def save_world_state(body: WorldStateSaveRequest, project_id: str = "default"):
    p = _validate_path(body.file_path)
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        try:
            ws.save(str(p))
            return {"ok": True}
        except Exception as e:
            raise HTTPException(400, str(e))


@router.post("/reset")
def reset_world_state(project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        save_ws(project_id, WorldState())
    return {"ok": True}


# --- Characters ---

@router.get("/characters")
def list_characters(project_id: str = "default"):
    ws = get_ws(project_id)
    return {k: v.model_dump() for k, v in ws.characters.items()}


@router.post("/characters")
def add_character(body: CharacterCreate, project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        ws.add_character(body.name, body.description, body.traits)
        save_ws(project_id, ws)
    return {"ok": True}


@router.delete("/characters/{name}")
def delete_character(name: str, project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        if name not in ws.characters:
            raise HTTPException(404, f"Character '{name}' not found")
        del ws.characters[name]
        save_ws(project_id, ws)
    return {"ok": True}


# --- Chapter Summaries ---

@router.get("/summaries")
def list_summaries(project_id: str = "default"):
    ws = get_ws(project_id)
    return [ws.chapter_summaries[k] for k in sorted(ws.chapter_summaries.keys())]


@router.post("/summaries")
def add_summary(body: ChapterSummaryCreate, project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        ws.add_chapter_summary(body.chapter_number, body.summary)
        save_ws(project_id, ws)
    return {"ok": True}


# --- Foreshadowing ---

@router.get("/foreshadowing")
def list_foreshadowing(project_id: str = "default"):
    ws = get_ws(project_id)
    return [f.model_dump() for f in ws.foreshadowing_pool]


@router.post("/foreshadowing")
def add_foreshadowing(body: ForeshadowingCreate, project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        ws.add_foreshadowing(body.detail, body.related_chapter)
        save_ws(project_id, ws)
    return {"ok": True}


@router.put("/foreshadowing/{index}/status")
def update_foreshadowing_status(index: int, status: Literal["pending", "resolved", "invalid"], project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        if index < 0 or index >= len(ws.foreshadowing_pool):
            raise HTTPException(404, "Foreshadowing index out of range")
        ws.foreshadowing_pool[index].status = status
        save_ws(project_id, ws)
    return {"ok": True}


@router.delete("/foreshadowing/{index}")
def delete_foreshadowing(index: int, project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        if index < 0 or index >= len(ws.foreshadowing_pool):
            raise HTTPException(404, "Foreshadowing index out of range")
        ws.foreshadowing_pool.pop(index)
        save_ws(project_id, ws)
    return {"ok": True}


# --- Relationships ---

class RelationshipCreate(BaseModel):
    char1: str
    char2: str
    relation_type: str
    description: str = ""


@router.get("/relationships")
def list_relationships(project_id: str = "default"):
    ws = get_ws(project_id)
    return {k: v.model_dump() for k, v in ws.relationships.items()}


@router.post("/relationships")
def add_relationship(body: RelationshipCreate, project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        ws.add_relationship(body.char1, body.char2, body.relation_type, body.description)
        save_ws(project_id, ws)
    return {"ok": True}


@router.delete("/relationships/{key}")
def delete_relationship(key: str, project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        if key not in ws.relationships:
            raise HTTPException(404, f"Relationship '{key}' not found")
        del ws.relationships[key]
        save_ws(project_id, ws)
    return {"ok": True}


# --- Plot Threads ---

class PlotThreadCreate(BaseModel):
    name: str
    description: str = ""
    thread_type: str = "subplot"


@router.get("/plot-threads")
def list_plot_threads(project_id: str = "default"):
    ws = get_ws(project_id)
    return [t.model_dump() for t in ws.plot_threads]


@router.post("/plot-threads")
def add_plot_thread(body: PlotThreadCreate, project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        ws.add_plot_thread(body.name, body.description, body.thread_type)
        save_ws(project_id, ws)
    return {"ok": True}


# --- Tropes ---

class TropeCreate(BaseModel):
    trope: str


@router.get("/tropes")
def list_tropes(project_id: str = "default"):
    ws = get_ws(project_id)
    return list(ws.used_tropes)


@router.post("/tropes")
def add_trope(body: TropeCreate, project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        ws.add_used_trope(body.trope)
        save_ws(project_id, ws)
    return {"ok": True}


@router.delete("/tropes/{index}")
def delete_trope(index: int, project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        if index < 0 or index >= len(ws.used_tropes):
            raise HTTPException(404, "Trope index out of range")
        ws.used_tropes.pop(index)
        save_ws(project_id, ws)
    return {"ok": True}


# --- Narrative Strategy Profile ---

class NarrativeProfileUpdate(BaseModel):
    source_book: str = ""
    chapter_function_pattern: str = ""
    pov_pattern: str = ""
    foreshadowing_density: str = ""
    multiline_style: str = ""
    info_release: str = ""
    tension_template: str = ""
    conflict_escalation: str = ""
    emotional_rhythm: str = ""
    chapter_structure: str = ""


@router.get("/narrative-profile")
def get_narrative_profile(project_id: str = "default"):
    ws = get_ws(project_id)
    if ws.narrative_profile:
        return ws.narrative_profile.model_dump()
    return None


@router.put("/narrative-profile")
def update_narrative_profile(body: NarrativeProfileUpdate, project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        from inkflow.memory.narrative_profile import NarrativeStrategyProfile
        if ws.narrative_profile is None:
            ws.narrative_profile = NarrativeStrategyProfile()
        # Use model_copy for safe, validated update
        ws.narrative_profile = ws.narrative_profile.model_copy(update=body.model_dump(exclude_none=True))
        save_ws(project_id, ws)
    return {"ok": True}


@router.post("/narrative-profile/from-analysis")
def set_narrative_profile_from_analysis(analysis: dict, project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        from inkflow.memory.narrative_profile import NarrativeStrategyProfile
        ws.narrative_profile = NarrativeStrategyProfile.from_analysis(analysis)
        save_ws(project_id, ws)
    return {"ok": True, "profile": ws.narrative_profile.model_dump()}


@router.delete("/narrative-profile")
def clear_narrative_profile(project_id: str = "default"):
    lock = _get_project_lock(project_id)
    with lock:
        ws = get_ws(project_id)
        ws.narrative_profile = None
        save_ws(project_id, ws)
    return {"ok": True}