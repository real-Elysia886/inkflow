"""Skill management API router."""

import json
import re
import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import Response

from inkflow.api.schemas.skill import (
    SkillCreate, SkillUpdate, SkillOut,
    SkillDetailOut, SkillRunRequest, SkillRunResult,
)
from inkflow.skill_engine.skill_writer import create_skill, update_skill, list_skills, slugify
from inkflow.skill_engine.skill_presets import resolve_storage_root, get_skill_preset, list_skill_types
from inkflow.skill_engine.version_manager import list_versions, rollback, cleanup_old_versions
from inkflow.skill_engine.registry import SkillRegistry

router = APIRouter(prefix="/api/skills", tags=["skills"])

# Cached registry (invalidated on create/delete) — delegates to the
# process-wide SkillRegistry singleton so other modules see updates too.


def _base_dir() -> Path:
    return resolve_storage_root()


def _validate_slug(skill_type: str, slug: str) -> Path:
    """Validate and resolve skill path, preventing traversal."""
    if not re.match(r'^[\w\-]+$', skill_type) or not re.match(r'^[\w\-]+$', slug):
        raise HTTPException(400, "Invalid skill_type or slug (alphanumeric/hyphens/underscores only)")
    base = _base_dir()
    # Base skill: skill_type == slug → path is base/skill_type
    # Nested skill: skill_type != slug → path is base/skill_type/slug
    if slug == skill_type:
        skill_dir = (base / skill_type).resolve()
    else:
        skill_dir = (base / skill_type / slug).resolve()
    if not skill_dir.is_relative_to(base.resolve()):
        raise HTTPException(400, "Path traversal detected")
    return skill_dir


def _get_registry() -> SkillRegistry:
    return SkillRegistry.get_default()


def _invalidate_registry():
    SkillRegistry.invalidate_default()


@router.get("/types")
def get_skill_types():
    types = []
    for t in list_skill_types():
        preset = get_skill_preset(t)
        types.append({
            "type": t,
            "display_name": preset["display_name"],
            "description": preset["description"],
            "default_provider": preset["default_provider"],
            "default_model": preset["default_model"],
        })
    return types


@router.get("", response_model=list[SkillOut])
def get_skills(skill_type: str = None):
    skills = list_skills(_base_dir())
    if skill_type:
        skills = [s for s in skills if s["skill_type"] == skill_type]
    return [SkillOut(**s) for s in skills]


@router.post("", response_model=SkillOut)
def create_new_skill(body: SkillCreate):
    base = _base_dir()
    preset = get_skill_preset(body.skill_type)
    slug_str = slugify(body.slug or body.display_name or "unnamed")

    meta = {
        "skill_type": body.skill_type,
        "display_name": body.display_name or preset["display_name"],
        "description": body.description or preset["description"],
        "provider": body.provider or preset["default_provider"],
        "model": body.model or preset["default_model"],
        "temperature": body.temperature if body.temperature is not None else preset["default_temperature"],
        "max_tokens": body.max_tokens or preset["default_max_tokens"],
    }
    if body.prompt_content:
        meta["prompt_content"] = body.prompt_content
    if body.samples_content:
        meta["samples_content"] = body.samples_content

    create_skill(base, slug_str, meta, body.agent_code)
    _invalidate_registry()

    # Build response directly from meta (no re-listing)
    from inkflow.skill_engine.skill_schema import enrich_skill_meta, sync_legacy_fields
    meta = sync_legacy_fields(enrich_skill_meta(meta, slug_str, body.skill_type))
    lifecycle = meta.get("lifecycle", {})
    return SkillOut(
        slug=slug_str,
        skill_type=body.skill_type,
        name=meta.get("name", ""),
        display_name=meta.get("display_name", ""),
        description=meta.get("description", ""),
        version=lifecycle.get("version", "v1"),
        updated_at=lifecycle.get("updated_at", ""),
        corrections_count=lifecycle.get("corrections_count", 0),
        path=str(base / body.skill_type / slug_str),
    )


@router.get("/{skill_type}/{slug}", response_model=SkillDetailOut)
def get_skill_detail(skill_type: str, slug: str):
    skill_dir = _validate_slug(skill_type, slug)
    if not skill_dir.exists():
        raise HTTPException(404, f"Skill '{skill_type}/{slug}' not found")

    meta = {}
    meta_file = skill_dir / "meta.json"
    if meta_file.exists():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))

    files = {}
    for fname in ("agent.py", "config.yaml", "prompt.md", "samples.json"):
        fpath = skill_dir / fname
        if fpath.exists():
            files[fname] = fpath.read_text(encoding="utf-8")

    versions = list_versions(skill_dir)
    return SkillDetailOut(meta=meta, files=files, versions=versions)


@router.put("/{skill_type}/{slug}")
def update_existing_skill(skill_type: str, slug: str, body: SkillUpdate):
    skill_dir = _validate_slug(skill_type, slug)
    if not skill_dir.exists():
        raise HTTPException(404, f"Skill '{skill_type}/{slug}' not found")

    new_version = update_skill(skill_dir, body.agent_patch, body.prompt_patch, body.config_patch)
    _invalidate_registry()
    return {"ok": True, "version": new_version}


@router.delete("/{skill_type}/{slug}")
def delete_skill(skill_type: str, slug: str):
    skill_dir = _validate_slug(skill_type, slug)
    if not skill_dir.exists():
        raise HTTPException(404, f"Skill '{skill_type}/{slug}' not found")
    # Protect base/default skills from deletion
    base_skills = {"editor", "writer", "librarian", "strategist", "prophet"}
    if slug in base_skills and skill_type == slug:
        raise HTTPException(403, f"默认技能 '{skill_type}/{slug}' 不允许删除")
    shutil.rmtree(skill_dir)
    _invalidate_registry()
    return {"ok": True}


@router.get("/{skill_type}/{slug}/versions")
def get_skill_versions(skill_type: str, slug: str):
    skill_dir = _validate_slug(skill_type, slug)
    if not skill_dir.exists():
        raise HTTPException(404, f"Skill '{skill_type}/{slug}' not found")
    return list_versions(skill_dir)


@router.post("/{skill_type}/{slug}/rollback")
def rollback_skill(skill_type: str, slug: str, version: str):
    skill_dir = _validate_slug(skill_type, slug)
    if not skill_dir.exists():
        raise HTTPException(404, f"Skill '{skill_type}/{slug}' not found")
    success = rollback(skill_dir, version)
    if not success:
        raise HTTPException(400, f"Rollback to '{version}' failed")
    _invalidate_registry()
    return {"ok": True}


@router.post("/{skill_type}/{slug}/cleanup")
def cleanup_skill(skill_type: str, slug: str, max_versions: int = 10):
    if max_versions < 1 or max_versions > 100:
        raise HTTPException(400, "max_versions must be between 1 and 100")
    skill_dir = _validate_slug(skill_type, slug)
    if not skill_dir.exists():
        raise HTTPException(404, f"Skill '{skill_type}/{slug}' not found")
    cleanup_old_versions(skill_dir, max_versions)
    return {"ok": True}


@router.post("/{skill_type}/{slug}/files/{filename}")
async def update_skill_file(skill_type: str, slug: str, filename: str, request: Request):
    allowed = {"prompt.md", "config.yaml", "samples.json", "agent.py"}
    if filename not in allowed:
        raise HTTPException(400, f"Cannot edit '{filename}'. Allowed: {allowed}")

    skill_dir = _validate_slug(skill_type, slug)
    if not skill_dir.exists():
        raise HTTPException(404, "Skill not found")

    content = (await request.body()).decode("utf-8")
    fpath = skill_dir / filename
    fpath.write_text(content, encoding="utf-8")
    _invalidate_registry()
    return {"ok": True}


@router.post("/run", response_model=SkillRunResult)
def run_skill(body: SkillRunRequest):
    from inkflow.memory.world_state import WorldState

    registry = _get_registry()

    info = registry.get(body.skill_type, body.slug)
    if not info:
        raise HTTPException(404, f"Skill '{body.skill_type}/{body.slug}' not found or not loadable")

    try:
        agent = info.instantiate()
    except Exception as e:
        return SkillRunResult(success=False, error=f"Failed to instantiate: {e}")

    if body.world_state:
        ws = WorldState.from_dict(body.world_state)
    else:
        ws = WorldState()

    try:
        result = agent.execute(ws, **body.kwargs)
        return SkillRunResult(success=True, result=result)
    except Exception as e:
        return SkillRunResult(success=False, error=str(e))


@router.get("/{skill_type}/{slug}/export")
def export_skill(skill_type: str, slug: str):
    """Export a skill as a .inkflow-skill zip package."""
    skill_dir = _validate_slug(skill_type, slug)
    if not skill_dir.exists():
        raise HTTPException(404, f"Skill '{skill_type}/{slug}' not found")

    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Include all skill files
        for fpath in sorted(skill_dir.rglob("*")):
            if fpath.is_file() and "versions" not in fpath.parts:
                arcname = fpath.relative_to(skill_dir)
                zf.write(fpath, arcname)
        # Add package metadata
        zf.writestr("package.json", json.dumps({
            "format": "inkflow-skill",
            "version": "1.0",
            "skill_type": skill_type,
            "slug": slug,
        }, ensure_ascii=False, indent=2))

    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.inkflow-skill"'},
    )


@router.post("/import")
async def import_skill(file: UploadFile = File(...), skill_type: str = None, slug: str = None):
    """Import a skill from a .inkflow-skill zip package."""
    if not file.filename.endswith(".inkflow-skill") and not file.filename.endswith(".zip"):
        raise HTTPException(400, "File must be a .inkflow-skill or .zip package")

    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(413, "Package too large (max 10MB)")

    try:
        buf = BytesIO(raw)
        with zipfile.ZipFile(buf, 'r') as zf:
            # Read package metadata if present
            pkg_meta = {}
            if "package.json" in zf.namelist():
                pkg_meta = json.loads(zf.read("package.json"))

            # Determine target skill_type and slug
            target_type = skill_type or pkg_meta.get("skill_type")
            target_slug = slug or pkg_meta.get("slug") or file.filename.replace(".inkflow-skill", "").replace(".zip", "")

            if not target_type:
                raise HTTPException(400, "skill_type not specified and not found in package")

            target_slug = slugify(target_slug)
            base = _base_dir()
            skill_dir = base / target_type / target_slug

            if skill_dir.exists():
                raise HTTPException(409, f"Skill '{target_type}/{target_slug}' already exists. Delete it first or use a different slug.")

            skill_dir.mkdir(parents=True, exist_ok=True)

            # Extract files
            for name in zf.namelist():
                if name == "package.json":
                    continue
                if name.endswith("/"):
                    (skill_dir / name).mkdir(parents=True, exist_ok=True)
                    continue
                data = zf.read(name)
                out_path = skill_dir / name
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(data)

        _invalidate_registry()
        return {"ok": True, "skill_type": target_type, "slug": target_slug, "path": str(skill_dir)}

    except zipfile.BadZipFile:
        raise HTTPException(400, "Invalid zip file")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Import failed: {e}")
