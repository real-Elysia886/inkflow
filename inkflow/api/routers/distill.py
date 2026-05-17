"""Book distillation API router."""

import asyncio
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from inkflow.distiller.book_analyzer import BookAnalyzer, split_book
from inkflow.distiller.skill_generator import SkillGenerator, build_skill_meta
from inkflow.skill_engine.skill_writer import create_skill
from inkflow.skill_engine.skill_presets import resolve_storage_root
from inkflow.utils.llm_utils import call_llm, parse_json_response

router = APIRouter(prefix="/api/distill", tags=["distill"])


class ModelOverride(BaseModel):
    """Optional model configuration override for distill jobs."""
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

# Thread-safe job store with disk persistence
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_jobs_dir = Path(__file__).parent.parent.parent.parent / "data" / "distill_jobs"
_jobs_dir.mkdir(parents=True, exist_ok=True)


def _save_job(job: dict):
    """Persist a job to disk."""
    path = _jobs_dir / f"{job['id']}.json"
    # Don't persist the full text (too large); only metadata
    saveable = {k: v for k, v in job.items() if k != "text"}
    
    # Sanitize api_key if present
    if "model_override" in saveable and "api_key" in saveable["model_override"]:
        key = saveable["model_override"]["api_key"]
        if key and len(key) > 8:
            saveable["model_override"]["api_key"] = key[:4] + "*" * (len(key)-8) + key[-4:]
        else:
            saveable["model_override"]["api_key"] = "****"
            
    path.write_text(json.dumps(saveable, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_job(job_id: str) -> Dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"Job '{job_id}' not found")
    return job


@router.post("/upload")
async def upload_book(
    file: UploadFile = File(None),
    text: str = Form(None),
):
    """Upload a book for distillation. Accepts file upload or raw text."""
    content = None

    if file:
        # Read with size limit
        raw = b""
        while True:
            chunk = await file.read(1024 * 1024)  # 1MB chunks
            if not chunk:
                break
            raw += chunk
            if len(raw) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"File too large (max {MAX_UPLOAD_BYTES // 1024 // 1024} MB)")
        for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                content = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if content is None:
            raise HTTPException(400, "Could not decode file. Please use UTF-8 or GBK encoding.")
    elif text:
        if len(text.encode("utf-8")) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"Text too large (max {MAX_UPLOAD_BYTES // 1024 // 1024} MB)")
        content = text
    else:
        raise HTTPException(400, "Please provide a file or text content")

    if len(content.strip()) < 100:
        raise HTTPException(400, "Text is too short (minimum 100 characters)")

    job_id = str(uuid.uuid4())[:8]
    chunk_count = len(split_book(content))
    job = {
        "id": job_id,
        "status": "uploaded",
        "text": content,
        "text_length": len(content),
        "chunk_count": chunk_count,
        "analysis": None,
        "generated_skills": None,
        "progress": [],
    }

    with _jobs_lock:
        _jobs[job_id] = job
    _save_job(job)

    return {"job_id": job_id, "text_length": len(content), "chunk_count": chunk_count}


@router.post("/{job_id}/analyze")
async def start_analysis(job_id: str, model: Optional[ModelOverride] = None):
    """Start book analysis. Optionally override the LLM model for this job."""
    job = _get_job(job_id)
    if job["status"] not in ("uploaded", "analyzed"):
        raise HTTPException(400, f"Job is in '{job['status']}' state, cannot analyze")

    # Store model override in job for persistence across retries
    if model:
        override = model.model_dump(exclude_none=True)
        if override:
            with _jobs_lock:
                job["model_override"] = override
            _save_job(job)

    model_override = job.get("model_override")

    def progress_cb(current, total, message):
        with _jobs_lock:
            job["progress"].append({"current": current, "total": total, "message": message})
            if len(job["progress"]) > 100:
                job["progress"] = job["progress"][-100:]

    def _run():
        analyzer = BookAnalyzer(model_override=model_override)
        return analyzer.analyze_book(job["text"], progress_callback=progress_cb)

    try:
        analysis = await asyncio.to_thread(_run)
        with _jobs_lock:
            job["analysis"] = analysis
            job["status"] = "analyzed"
            job["text"] = None  # Free memory after analysis
        _save_job(job)
        return {"ok": True, "analysis": analysis}
    except Exception as e:
        with _jobs_lock:
            job["status"] = "error"
            job["error"] = str(e)
        _save_job(job)
        raise HTTPException(500, f"Analysis failed: {e}")


@router.post("/{job_id}/generate")
async def start_generation(job_id: str, book_title: str = "蒸馏作品",
                           model: Optional[ModelOverride] = None):
    """Generate all 5 skills. Optionally override the LLM model for this job."""
    job = _get_job(job_id)
    if job["status"] not in ("analyzed", "error"):
        raise HTTPException(400, f"Job is in '{job['status']}' state, need 'analyzed' or 'error' first")
    if not job["analysis"]:
        raise HTTPException(400, "No analysis available")

    # Update model override if provided
    if model:
        override = model.model_dump(exclude_none=True)
        if override:
            with _jobs_lock:
                job["model_override"] = override
            _save_job(job)

    model_override = job.get("model_override")

    # Resume: keep already-generated skills
    existing = job.get("generated_skills") or {}

    def progress_cb(current, total, message):
        with _jobs_lock:
            job["progress"].append({"current": current, "total": total, "message": message})
            if len(job["progress"]) > 100:
                job["progress"] = job["progress"][-100:]

    def _run():
        generator = SkillGenerator(model_override=model_override)
        return generator.generate_all_skills(
            job["analysis"], book_title, progress_cb, skip=set(existing.keys())
        )

    try:
        with _jobs_lock:
            job["status"] = "generating"
        generated = (await asyncio.to_thread(_run)) or {}
        generated.update(existing)  # merge: new results + previously completed
        with _jobs_lock:
            job["generated_skills"] = generated
            job["book_title"] = book_title
            job["status"] = "generated"
        _save_job(job)
        return {"ok": True, "skills": {k: {"description": v["description"]} for k, v in generated.items()}}
    except Exception as e:
        with _jobs_lock:
            job["status"] = "error"
            job["error"] = str(e)
        _save_job(job)
        raise HTTPException(500, f"Generation failed: {e}")


@router.post("/{job_id}/install")
async def install_skills(job_id: str, slug_prefix: str = ""):
    """Install generated skills into the skills/ directory."""
    job = _get_job(job_id)
    if job["status"] != "generated":
        raise HTTPException(400, f"Job is in '{job['status']}' state, need 'generated' first")
    if not job["generated_skills"]:
        raise HTTPException(400, "No generated skills available")

    base_dir = resolve_storage_root()
    book_title = job.get("book_title", "distilled")
    prefix = slug_prefix or book_title.lower().replace(" ", "-")[:20]

    installed = []
    for skill_type, generated in job["generated_skills"].items():
        slug = f"{prefix}-{skill_type}"
        meta = build_skill_meta(skill_type, book_title, job["analysis"], generated)
        try:
            skill_dir = create_skill(base_dir, slug, meta)
            installed.append({"skill_type": skill_type, "slug": slug, "path": str(skill_dir)})
        except Exception as e:
            installed.append({"skill_type": skill_type, "error": str(e)})

    with _jobs_lock:
        job["status"] = "installed"
        job["installed"] = installed
    _save_job(job)
    return {"ok": True, "installed": installed}


@router.get("/{job_id}")
def get_job_status(job_id: str):
    job = _get_job(job_id)
    result = {
        "id": job["id"],
        "status": job["status"],
        "text_length": job["text_length"],
        "chunk_count": job["chunk_count"],
        "progress": job["progress"],
        "model_override": job.get("model_override"),
    }
    if job.get("error"):
        result["error"] = job["error"]
    if job.get("analysis"):
        result["analysis_summary"] = {
            "book_title": job["analysis"].get("book_title", ""),
            "genre": job["analysis"].get("genre", ""),
            "overall_style": job["analysis"].get("overall_style", ""),
        }
    if job.get("generated_skills"):
        result["skills"] = {
            k: {"description": v["description"]} for k, v in job["generated_skills"].items()
        }
    if job.get("installed"):
        result["installed"] = job["installed"]
    return result


@router.get("/{job_id}/analysis")
def get_analysis(job_id: str):
    job = _get_job(job_id)
    if not job.get("analysis"):
        raise HTTPException(404, "No analysis available")
    return job["analysis"]


@router.get("/{job_id}/skills/{skill_type}")
def get_generated_skill(job_id: str, skill_type: str):
    job = _get_job(job_id)
    if not job.get("generated_skills"):
        raise HTTPException(404, "No generated skills available")
    skill = job["generated_skills"].get(skill_type)
    if not skill:
        raise HTTPException(404, f"Skill type '{skill_type}' not found")
    return skill


class MultiBookRequest(BaseModel):
    """Request for multi-book style fusion."""
    job_ids: List[str]  # List of analysis job IDs to fuse
    book_title: str = "融合风格"
    weights: Optional[List[float]] = None  # Optional weights per book


@router.post("/fuse")
async def fuse_styles(body: MultiBookRequest, model: Optional[ModelOverride] = None):
    """Fuse style analyses from multiple books into a unified style."""
    if len(body.job_ids) < 2:
        raise HTTPException(400, "Need at least 2 job IDs for style fusion")
    if body.weights and len(body.weights) != len(body.job_ids):
        raise HTTPException(400, "weights length must match job_ids length")

    # Collect analyses
    analyses = []
    for jid in body.job_ids:
        job = _get_job(jid)
        if not job.get("analysis"):
            raise HTTPException(400, f"Job '{jid}' has no analysis. Run analysis first.")
        analyses.append(job["analysis"])

    model_override = (model.model_dump(exclude_none=True) if model else None)

    def _run():
        # Use LLM to fuse multiple analyses
        import json as _json
        analyses_text = _json.dumps(analyses, ensure_ascii=False, indent=2)
        if len(analyses_text) > 20000:
            analyses_text = analyses_text[:20000] + "\n... (truncated)"

        weights_info = ""
        if body.weights:
            weights_info = f"\n权重分配（越重要权重越高）: {dict(zip(body.job_ids, body.weights))}"

        prompt = f"""你是一位专业的文学分析师。请将以下多本书的风格分析融合为一个统一的创作风格。

{weights_info}

各书分析结果：
---
{analyses_text}
---

要求：
1. 提取各书的共同风格特征作为核心风格
2. 取各书精华，融合为一个完整、可执行的风格指南
3. 保留各书的独特亮点作为可选风格元素
4. 输出综合报告 JSON，格式与单书分析相同

输出合法 JSON（json object）："""

        raw = call_llm(prompt, role_name="prophet", temperature=0.3,
                       model_override=model_override)
        return parse_json_response(raw)

    try:
        fused = await asyncio.to_thread(_run)

        # Create a new job for the fused result
        job_id = str(uuid.uuid4())[:8]
        job = {
            "id": job_id,
            "status": "analyzed",
            "text": None,
            "text_length": 0,
            "chunk_count": 0,
            "analysis": fused,
            "generated_skills": None,
            "progress": [],
            "fused_from": body.job_ids,
            "book_title": body.book_title,
        }
        with _jobs_lock:
            _jobs[job_id] = job
        _save_job(job)

        return {"ok": True, "job_id": job_id, "analysis": fused}
    except Exception as e:
        raise HTTPException(500, f"Style fusion failed: {e}")


class StyleVersionRequest(BaseModel):
    """Save a named style version from an analysis job."""
    job_id: str
    style_name: str  # User-friendly name like "金庸风" or "轻松日常"
    description: str = ""


# In-memory style library (persisted to disk)
_style_library: Dict[str, Dict[str, Any]] = {}
_style_library_file = Path(__file__).parent.parent.parent.parent / "data" / "style_library.json"


def _load_style_library():
    global _style_library
    if _style_library_file.exists():
        try:
            _style_library = json.loads(_style_library_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            _style_library = {}


def _save_style_library():
    _style_library_file.parent.mkdir(parents=True, exist_ok=True)
    _style_library_file.write_text(
        json.dumps(_style_library, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@router.post("/styles/save")
def save_style_version(body: StyleVersionRequest):
    """Save a named style version from an analysis job to the style library."""
    job = _get_job(body.job_id)
    if not job.get("analysis"):
        raise HTTPException(400, "Job has no analysis")

    _load_style_library()
    style_id = body.style_name.lower().replace(" ", "-")[:30]
    _style_library[style_id] = {
        "name": body.style_name,
        "description": body.description,
        "analysis": job["analysis"],
        "source_job_id": body.job_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_style_library()
    return {"ok": True, "style_id": style_id}


@router.get("/styles")
def list_style_versions():
    """List all saved style versions."""
    _load_style_library()
    return [
        {"id": sid, "name": s["name"], "description": s.get("description", ""),
         "created_at": s.get("created_at", "")}
        for sid, s in _style_library.items()
    ]


@router.get("/styles/{style_id}")
def get_style_version(style_id: str):
    """Get a specific style version's full analysis."""
    _load_style_library()
    if style_id not in _style_library:
        raise HTTPException(404, f"Style '{style_id}' not found")
    return _style_library[style_id]


@router.delete("/styles/{style_id}")
def delete_style_version(style_id: str):
    """Delete a saved style version."""
    _load_style_library()
    if style_id not in _style_library:
        raise HTTPException(404, f"Style '{style_id}' not found")
    del _style_library[style_id]
    _save_style_library()
    return {"ok": True}
