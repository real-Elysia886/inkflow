"""Pipeline API - Asynchronous one-click chapter generation with job tracking."""

import asyncio
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from inkflow.pipeline.pipeline import ChapterPipeline
from inkflow.api.deps import _pm, get_ws, save_ws
from inkflow.api.ws_manager import ws_manager
from inkflow.api.routers.world import _get_project_lock
from inkflow.utils.atomic_io import write_json_atomic

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

# In-memory job tracking with TTL cleanup. Terminal states are also persisted
# under data/jobs/ so the UI can still query them after _JOB_TTL elapses.
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_JOB_TTL = 3600  # 1 hour

_JOBS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "jobs"
_JOBS_DIR.mkdir(parents=True, exist_ok=True)
# Keys that aren't JSON-serializable / shouldn't be persisted.
_NON_PERSISTABLE_KEYS = {"pipeline"}


def _persist_job(job: Dict[str, Any]) -> None:
    """Snapshot a job to disk (terminal states only)."""
    try:
        snapshot = {k: v for k, v in job.items() if k not in _NON_PERSISTABLE_KEYS}
        write_json_atomic(_JOBS_DIR / f"{job['job_id']}.json", snapshot)
    except Exception as e:
        print(f"[Job] Persist failed for {job.get('job_id')}: {e}")


def _load_persisted_job(job_id: str) -> Optional[Dict[str, Any]]:
    path = _JOBS_DIR / f"{job_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _cleanup_expired_jobs():
    """Remove jobs older than TTL. Terminal jobs are persisted to disk
    before eviction so the status endpoint can still serve them."""
    now = time.time()
    with _jobs_lock:
        expired = [jid for jid, j in _jobs.items() if now - j.get("created_at", 0) > _JOB_TTL]
        for jid in expired:
            job = _jobs.pop(jid, None)
            if job and job.get("status") in ("completed", "failed", "cancelled"):
                _persist_job(job)

class GenerateRequest(BaseModel):
    outline: Optional[Dict[str, Any]] = None
    project_id: str = "default"
    speed_mode: str = "standard"
    skill_map: Optional[Dict[str, str]] = None  # {"editor": "distilled-editor", ...}

class JobStatus(BaseModel):
    job_id: str
    status: str  # running | completed | failed
    progress: List[Dict[str, str]]
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

def _run_pipeline_task(job_id: str, body: GenerateRequest):
    """Background task runner for pipeline."""
    pm = _pm

    try:
        # 1. Load context
        ws = pm.get_world_state(body.project_id)
        project = pm.get_project(body.project_id)
        if not ws:
            raise ValueError(f"World state not found for project '{body.project_id}'")
        if not project:
            raise ValueError(f"Project '{body.project_id}' not found")

        def progress_cb(stage: str, msg: str):
            with _jobs_lock:
                if job_id not in _jobs:
                    return
                if stage == "writer_stream":
                    ws_manager.broadcast(job_id, {"type": "stream_chunk", "data": {"chunk": msg}})
                    return
                progress_item = {"stage": stage, "message": msg}
                _jobs[job_id]["progress"].append(progress_item)
                _jobs[job_id]["last_stage"] = stage
                ws_manager.broadcast(job_id, {"type": "progress", "data": progress_item})

        # 2. Setup pipeline
        skill_map = body.skill_map or project.skill_map
        pipeline = ChapterPipeline(skill_map=skill_map or None, project_dir=project.dir)
        pipeline.on_progress(progress_cb)
        pipeline.set_job_context(job_id, project.dir)

        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["pipeline"] = pipeline

        # 3. Run pipeline based on mode
        lock = _get_project_lock(body.project_id)

        if body.speed_mode == "full_auto":
            # Full auto: run all steps, save immediately, no human review
            with lock:
                result = pipeline.generate_chapter(
                    ws, body.outline,
                    speed_mode="full_auto",
                )

            if result.get("cancelled"):
                with _jobs_lock:
                    if job_id in _jobs:
                        _jobs[job_id]["status"] = "cancelled"
                        _jobs[job_id].pop("pipeline", None)
                        ws_manager.broadcast(job_id, {"type": "cancelled", "data": {}})
                        _persist_job(_jobs[job_id])
                return

            with lock:
                pm.save_world_state(body.project_id, ws)
                project.add_chapter(result)

            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id]["status"] = "completed"
                    _jobs[job_id].pop("pipeline", None)
                    _jobs[job_id]["result"] = {
                        "chapter_number": result["chapter_number"],
                        "outline": result["outline"],
                        "evaluation": result["evaluation"],
                        "final_text": result["final_text"],
                        "passed": result["passed"],
                        "retries": result["retries"],
                    }
                    ws_manager.broadcast(job_id, {"type": "completed", "data": _jobs[job_id]["result"]})
                    _persist_job(_jobs[job_id])
        else:
            # Normal mode: preview only (steps 1-6, no save)
            with lock:
                result = pipeline.generate_chapter_preview(
                    ws, body.outline,
                    speed_mode=body.speed_mode,
                )

            if result.get("cancelled"):
                with _jobs_lock:
                    if job_id in _jobs:
                        _jobs[job_id]["status"] = "cancelled"
                        _jobs[job_id].pop("pipeline", None)
                        ws_manager.broadcast(job_id, {"type": "cancelled", "data": {}})
                        _persist_job(_jobs[job_id])
                return

            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id]["status"] = "preview_ready"
                    _jobs[job_id]["preview"] = {
                        "chapter_number": result["chapter_number"],
                        "outline": result["outline"],
                        "evaluation": result["evaluation"],
                        "final_text": result["final_text"],
                        "passed": result["passed"],
                        "retries": result["retries"],
                    }
                    _jobs[job_id]["project_id"] = body.project_id
                    ws_manager.broadcast(job_id, {"type": "preview_ready", "data": _jobs[job_id]["preview"]})
                
    except Exception as e:
        import traceback
        # Full trace to server log; trimmed message to client.
        traceback.print_exc()
        error_msg = str(e) or e.__class__.__name__
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "failed"
                _jobs[job_id]["error"] = error_msg
                _jobs[job_id].pop("pipeline", None)
                ws_manager.broadcast(job_id, {"type": "failed", "data": {"error": error_msg}})
                _persist_job(_jobs[job_id])

@router.post("/generate")
async def generate_chapter(body: GenerateRequest, background_tasks: BackgroundTasks):
    """Start an asynchronous chapter generation job."""
    _cleanup_expired_jobs()
    job_id = str(uuid.uuid4())[:8]

    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "running",
            "progress": [],
            "last_stage": "init",
            "result": None,
            "error": None,
            "created_at": time.time(),
            "project_id": body.project_id,
        }
    
    background_tasks.add_task(_run_pipeline_task, job_id, body)

    return {"job_id": job_id, "status": "running"}


@router.post("/cancel/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a running pipeline job."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, f"Job {job_id} not found")
        if job.get("status") not in ("running",):
            raise HTTPException(400, f"Job is in '{job.get('status')}' state, cannot cancel")

    pipeline = job.get("pipeline")
    if pipeline:
        pipeline.cancel()

    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "cancelled"
            _jobs[job_id].pop("pipeline", None)
            ws_manager.broadcast(job_id, {"type": "cancelled", "data": {}})
            _persist_job(_jobs[job_id])

    return {"ok": True, "status": "cancelled"}


class ConfirmRequest(BaseModel):
    job_id: str
    project_id: str = "default"
    edited_text: str = ""  # User-edited text (optional, uses original if empty)


@router.post("/confirm")
async def confirm_chapter(body: ConfirmRequest):
    """Confirm human review and run post-review pipeline steps (ObserveReflect + Librarian)."""
    with _jobs_lock:
        job = _jobs.get(body.job_id)

    if not job:
        raise HTTPException(404, f"Job '{body.job_id}' not found")
    if job.get("status") != "preview_ready":
        raise HTTPException(400, f"Job is in '{job.get('status')}' state, need 'preview_ready'")

    preview = job.get("preview")
    if not preview:
        raise HTTPException(400, "No preview result available")

    def _run():
        pm = _pm
        ws = pm.get_world_state(body.project_id)
        project = pm.get_project(body.project_id)
        final_text = body.edited_text if body.edited_text else preview["final_text"]

        def progress_cb(stage: str, msg: str):
            with _jobs_lock:
                if body.job_id in _jobs:
                    progress_item = {"stage": stage, "message": msg}
                    _jobs[body.job_id]["progress"].append(progress_item)
                    ws_manager.broadcast(body.job_id, {"type": "progress", "data": progress_item})

        pipeline = ChapterPipeline(project_dir=project.dir if project else None)
        pipeline.on_progress(progress_cb)

        lock = _get_project_lock(body.project_id)
        with lock:
            result = pipeline.confirm_chapter(
                world_state=ws,
                chapter_number=preview["chapter_number"],
                final_text=final_text,
                plan=preview.get("outline") or preview.get("plan") or {},
                evaluation=preview.get("evaluation") or {},
            )
            pm.save_world_state(body.project_id, ws)
            project.add_chapter(result)

        with _jobs_lock:
            if body.job_id in _jobs:
                _jobs[body.job_id]["status"] = "completed"
                _jobs[body.job_id].pop("pipeline", None)
                _jobs[body.job_id]["result"] = {
                    "chapter_number": result["chapter_number"],
                    "outline": result.get("outline"),
                    "evaluation": result.get("evaluation"),
                    "final_text": result.get("final_text"),
                    "passed": result.get("passed", False),
                    "retries": result.get("retries", 0),
                }
                ws_manager.broadcast(body.job_id, {"type": "completed", "data": _jobs[body.job_id]["result"]})
                _persist_job(_jobs[body.job_id])

        return result

    try:
        result = await asyncio.to_thread(_run)
        return {"ok": True, "chapter_number": result["chapter_number"]}
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = str(e) or e.__class__.__name__
        with _jobs_lock:
            if body.job_id in _jobs:
                _jobs[body.job_id]["status"] = "failed"
                _jobs[body.job_id]["error"] = error_msg
                _jobs[body.job_id].pop("pipeline", None)
                ws_manager.broadcast(body.job_id, {"type": "failed", "data": {"error": error_msg}})
                _persist_job(_jobs[body.job_id])
        raise HTTPException(500, f"Confirm failed: {error_msg}")


class RewriteRequest(BaseModel):
    job_id: str
    project_id: str = "default"
    reason: str  # User's reason for rejection


@router.post("/rewrite")
async def rewrite_chapter(body: RewriteRequest):
    """Reject the current draft and rewrite based on user feedback."""
    with _jobs_lock:
        job = _jobs.get(body.job_id)

    if not job:
        raise HTTPException(404, f"Job '{body.job_id}' not found")
    if job.get("status") != "preview_ready":
        raise HTTPException(400, f"Job is in '{job.get('status')}' state, need 'preview_ready'")

    preview = job.get("preview")
    if not preview:
        raise HTTPException(400, "No preview result available")

    pm = _pm
    ws = pm.get_world_state(body.project_id)
    if not ws:
        raise HTTPException(404, f"World state not found for project '{body.project_id}'")

    from inkflow.utils.llm_utils import call_llm, parse_json_response
    from inkflow.pipeline.anti_ai import build_anti_ai_prompt_section

    current_text = preview["final_text"]
    outline = preview.get("outline") or preview.get("plan") or {}
    outline_text = outline.get("chapter_goal", "")

    # Build rewrite prompt with user feedback
    chars = "\n".join(
        f"- {name}: {ch.description} ({ch.traits})"
        for name, ch in ws.characters.items()
    )

    rewrite_prompt = f"""请根据以下反馈重写章节。

## 世界观
{ws.world_setting or '（未设定）'}

## 角色
{chars or '（无角色）'}

## 大纲
{outline_text or '（无大纲）'}

## 用户审阅反馈（必须解决）
{body.reason}

{build_anti_ai_prompt_section()}

## 原文
{current_text}

请输出完整的重写后的章节正文。保留章节标题，根据用户反馈进行针对性修改。"""

    def progress_cb(stage: str, msg: str):
        with _jobs_lock:
            if body.job_id not in _jobs:
                return
            if stage == "writer_stream":
                ws_manager.broadcast(body.job_id, {"type": "stream_chunk", "data": {"chunk": msg}})
                return
            progress_item = {"stage": stage, "message": msg}
            _jobs[body.job_id]["progress"].append(progress_item)
            ws_manager.broadcast(body.job_id, {"type": "progress", "data": progress_item})

    def _run():
        progress_cb("rewrite", "根据反馈重写中...")
        new_text = call_llm(rewrite_prompt, role_name="writer", temperature=0.7,
                           max_tokens=8192, json_mode=False,
                           on_chunk=lambda c: progress_cb("writer_stream", c))

        from inkflow.pipeline.quality import QualityScorer
        from inkflow.pipeline.anti_ai import analyze_text
        quality = QualityScorer()
        ai_analysis = analyze_text(new_text)
        evaluation = quality.evaluate(new_text, outline_text, ws)
        evaluation["anti_ai_score"] = ai_analysis["score"]

        new_preview = {
            "chapter_number": preview["chapter_number"],
            "outline": outline,
            "evaluation": evaluation,
            "final_text": new_text,
            "passed": evaluation.get("pass", False),
            "retries": (preview.get("retries") or 0) + 1,
        }

        with _jobs_lock:
            if body.job_id in _jobs:
                _jobs[body.job_id]["status"] = "preview_ready"
                _jobs[body.job_id]["preview"] = new_preview
                ws_manager.broadcast(body.job_id, {"type": "preview_ready", "data": new_preview})

        return new_preview

    try:
        new_preview = await asyncio.to_thread(_run)
        return {"ok": True, "retries": new_preview["retries"]}
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = str(e) or e.__class__.__name__
        with _jobs_lock:
            if body.job_id in _jobs:
                _jobs[body.job_id]["status"] = "failed"
                _jobs[body.job_id]["error"] = error_msg
                _jobs[body.job_id].pop("pipeline", None)
                ws_manager.broadcast(body.job_id, {"type": "failed", "data": {"error": error_msg}})
                _persist_job(_jobs[body.job_id])
        raise HTTPException(500, f"Rewrite failed: {error_msg}")


class QuickStartRequest(BaseModel):
    project_id: str = "default"
    genre: str = ""
    keywords: str = ""
    protagonist: str = ""
    tone: str = ""


@router.post("/quick-start")
async def quick_start(body: QuickStartRequest):
    """Generate world setting, characters, and outlines from keywords."""
    from inkflow.utils.llm_utils import call_llm, parse_json_response

    ws = get_ws(body.project_id)

    prompt = f"""你是一位资深小说设定设计师。根据用户提供的关键词，生成完整的小说基础设定。

## 用户输入
- 类型: {body.genre or '（未指定）'}
- 关键词: {body.keywords or '（未指定）'}
- 主角描述: {body.protagonist or '（未指定）'}
- 基调: {body.tone or '（未指定）'}

请生成以下内容（输出合法 JSON）：
{{
  "world_setting": "详细的世界观设定（200-400字）",
  "characters": {{
    "角色名": {{"description": "角色描述", "traits": "性格特征"}}
  }},
  "author_intent": "故事的长期发展方向",
  "current_focus": "开篇阶段的关注点"
}}

要求：
1. world_setting 要具体，包含时代背景、核心设定、独特元素
2. 生成 2-4 个主要角色，各有鲜明特点
3. 角色之间要有关系张力
4. author_intent 要有明确的结局方向
5. current_focus 要具体到开篇几章的重点"""

    def _run():
        raw = call_llm(prompt, role_name="strategist", temperature=0.7, max_tokens=2048, json_mode=True)
        result = parse_json_response(raw)

        if result.get("world_setting"):
            ws.world_setting = result["world_setting"]
        if result.get("author_intent"):
            ws.author_intent = result["author_intent"]
        if result.get("current_focus"):
            ws.current_focus = result["current_focus"]
        if result.get("characters"):
            for name, info in result["characters"].items():
                ws.add_character(name, info.get("description", ""), info.get("traits", ""))

        from inkflow.pipeline.outline_writer import OutlineWriter
        ow = OutlineWriter()
        ws.outline_window = ow.cold_start(ws)

        save_ws(body.project_id, ws)
        _pm.get_project(body.project_id).save()
        _pm.invalidate_cache(body.project_id)

        return result

    result = await asyncio.to_thread(_run)
    return {"ok": True, "setting": result}


@router.get("/active-jobs/{project_id}")
async def get_active_jobs(project_id: str):
    """Return active (running or preview_ready) jobs for a project."""
    _cleanup_expired_jobs()
    with _jobs_lock:
        active = []
        for jid, job in _jobs.items():
            if job.get("project_id") == project_id and job.get("status") in ("running", "preview_ready"):
                active.append({
                    "job_id": jid,
                    "status": job["status"],
                    "created_at": job.get("created_at"),
                    "last_stage": job.get("last_stage", "init"),
                })
        return active


@router.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """Job progress channel.

    Server pings the client every 25s so idle proxies don't reap the
    connection. Client may send any message back (used as pong / keepalive);
    incoming text is otherwise ignored.
    """
    await ws_manager.connect(job_id, websocket)
    try:
        while True:
            try:
                # Wait for either a client message or the ping interval.
                await asyncio.wait_for(websocket.receive_text(), timeout=25)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        ws_manager.disconnect(job_id, websocket)

@router.get("/status/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Poll the status of a generation job.

    Falls back to the on-disk snapshot when the in-memory entry has expired.
    """
    _cleanup_expired_jobs()
    with _jobs_lock:
        if job_id in _jobs:
            return JobStatus(**_jobs[job_id])

    persisted = _load_persisted_job(job_id)
    if persisted is None:
        raise HTTPException(404, f"Job {job_id} not found")
    return JobStatus(**persisted)


class ImportChapterRequest(BaseModel):
    chapter_number: int = Field(..., ge=1)
    text: str = Field(..., min_length=50)
    title: str = ""
    extract_facts: bool = True
    project_id: str = "default"

@router.post("/import")
async def import_chapter(body: ImportChapterRequest):
    pm = _pm
    ws = pm.get_world_state(body.project_id)
    project = pm.get_project(body.project_id)

    observations = None
    observation_error = None
    if body.extract_facts:
        def _observe():
            from inkflow.pipeline.observer import Observer
            from inkflow.pipeline.reflector import Reflector
            obs = Observer().observe(body.text, ws)
            Reflector().apply(ws, obs, body.chapter_number)
            return obs

        try:
            observations = await asyncio.to_thread(_observe)
        except Exception as e:
            observation_error = str(e)
            print(f"[WARN] Observer failed during import: {e}")

    ws.add_chapter_meta(
        chapter_number=body.chapter_number,
        summary=body.text[:200],
        title=body.title or f"第{body.chapter_number}章",
        word_count=len(body.text),
    )
    if body.chapter_number > ws.current_chapter:
        ws.current_chapter = body.chapter_number

    pm.save_world_state(body.project_id, ws)
    project.add_chapter({
        "chapter_number": body.chapter_number,
        "final_text": body.text,
        "title": body.title,
        "passed": True,
        "imported": True,
    })
    return {
        "ok": True,
        "chapter_number": body.chapter_number,
        "current_chapter": ws.current_chapter,
        "observations_extracted": observations is not None,
        "observation_error": observation_error,
    }


class BatchImportRequest(BaseModel):
    chapters: List[Dict[str, Any]]
    project_id: str = "default"


@router.post("/import/batch")
async def batch_import_chapters(body: BatchImportRequest):
    """Import multiple chapters at once."""
    pm = _pm
    ws = pm.get_world_state(body.project_id)
    project = pm.get_project(body.project_id)

    def _run():
        imported = 0
        for ch in body.chapters:
            ch_num = ch.get("chapter_number", imported + 1)
            text = ch.get("text", "")
            title = ch.get("title", "")
            extract = ch.get("extract_facts", True)

            if len(text) < 50:
                continue

            if extract:
                try:
                    from inkflow.pipeline.observer import Observer
                    from inkflow.pipeline.reflector import Reflector
                    obs = Observer().observe(text, ws)
                    Reflector().apply(ws, obs, ch_num)
                except Exception as e:
                    print(f"[WARN] Observer failed for chapter {ch_num}: {e}")

            ws.add_chapter_meta(
                chapter_number=ch_num,
                summary=text[:200],
                title=title or f"第{ch_num}章",
                word_count=len(text),
            )
            if ch_num > ws.current_chapter:
                ws.current_chapter = ch_num

            project.add_chapter({
                "chapter_number": ch_num,
                "final_text": text,
                "title": title,
                "passed": True,
                "imported": True,
            })
            imported += 1
        return imported

    imported = await asyncio.to_thread(_run)
    pm.save_world_state(body.project_id, ws)
    return {
        "ok": True,
        "imported_count": imported,
        "current_chapter": ws.current_chapter,
    }
