"""Workbench API — Save-and-observe + chapter context for the writer workbench."""

import asyncio
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from inkflow.api.deps import get_ws, save_ws
from inkflow.skill_engine.registry import SkillRegistry

router = APIRouter(prefix="/api/workbench", tags=["workbench"])


def _get_registry() -> SkillRegistry:
    return SkillRegistry.get_default()


class SaveAndObserveRequest(BaseModel):
    chapter_number: int
    text: str
    project_id: str = "default"


class ChapterContextRequest(BaseModel):
    chapter_number: int
    project_id: str = "default"


@router.post("/save-and-observe")
async def save_and_observe(body: SaveAndObserveRequest):
    """Save chapter text and re-run Observer + Reflector to update truth files."""
    ws = get_ws(body.project_id)
    ch = body.chapter_number

    # Save chapter text
    from inkflow.api.deps import _pm
    _pm.save_chapter(body.project_id, ch, body.text)

    # Run Observer + Reflector
    from inkflow.pipeline.observer import Observer
    from inkflow.pipeline.reflector import Reflector

    def _run():
        observer = Observer()
        reflector = Reflector()
        observations = observer.observe(body.text, ws)
        reflector.apply(ws, observations, ch)
        return observations

    try:
        observations = await asyncio.to_thread(_run)
        save_ws(body.project_id, ws)
        return {"ok": True, "observations": observations}
    except Exception as e:
        raise HTTPException(500, f"Observer failed: {e}")


@router.post("/chapter-context")
async def get_chapter_context(body: ChapterContextRequest):
    """Get rich context for a chapter: characters, foreshadowing, outline, etc."""
    ws = get_ws(body.project_id)
    ch = body.chapter_number

    # Characters with their current state
    characters = {}
    for name, c in ws.characters.items():
        characters[name] = {
            "description": c.description,
            "traits": c.traits,
            "status": c.status,
            "notes": c.notes,
        }

    # Foreshadowing related to this chapter or pending
    foreshadowing = [
        f.model_dump() for f in ws.foreshadowing_pool
        if f.planted_chapter == ch or f.status == "pending"
    ]

    # Outline for this chapter
    outline = None
    o = ws.outline_window.get_outline(ch)
    if o:
        outline = o.to_dict()

    # Recent summaries
    recent = ws.get_recent_summaries(5)

    # Active plot threads
    threads = [
        {"name": t.name, "type": t.thread_type, "description": t.description, "status": t.status}
        for t in ws.get_active_plot_threads()
    ]

    # Author intent and focus
    governance = {
        "author_intent": ws.author_intent,
        "current_focus": ws.current_focus,
    }

    return {
        "chapter_number": ch,
        "characters": characters,
        "foreshadowing": foreshadowing,
        "outline": outline,
        "recent_summaries": recent,
        "plot_threads": threads,
        "governance": governance,
        "world_setting": ws.world_setting,
    }


@router.post("/run-review")
async def run_review(body: SaveAndObserveRequest):
    """Run Editor review on chapter text and return evaluation."""
    ws = get_ws(body.project_id)

    from inkflow.pipeline.quality import QualityScorer
    from inkflow.pipeline.anti_ai import analyze_text, generate_learning_examples
    from inkflow.skill_engine.registry import SkillRegistry

    def _run():
        from inkflow.api.deps import _pm
        project = _pm.get_project(body.project_id)
        skill_map = project.skill_map if project else {}

        registry = _get_registry()
        slug = skill_map.get("editor")
        if slug:
            info = registry.get("editor", slug)
        else:
            info = registry.get_preferred("editor")
        editor_agent = info.instantiate() if info else None
        if editor_agent:
            evaluation = editor_agent.execute(ws, body.text)
        else:
            qs = QualityScorer()
            evaluation = qs.evaluate(body.text, "", ws)

        ai_analysis = analyze_text(body.text)
        evaluation["anti_ai_score"] = ai_analysis["score"]
        evaluation["anti_ai_issues"] = ai_analysis["fatigue_words"][:5]
        learning = generate_learning_examples(ai_analysis, body.text)
        if learning:
            evaluation["anti_ai_learning"] = learning
        return evaluation

    try:
        evaluation = await asyncio.to_thread(_run)
        return {"ok": True, "evaluation": evaluation}
    except Exception as e:
        raise HTTPException(500, f"Review failed: {e}")


class AntiDetectRequest(BaseModel):
    text: str
    project_id: str = "default"
    custom_words: Optional[List[str]] = None  # additional fatigue words


class AntiDetectResponse(BaseModel):
    ok: bool
    score: int
    fatigue_words: list
    banned_patterns: list
    sentence_stats: dict
    dialogue_ratio: float
    rewritten_text: Optional[str] = None
    learning_examples: Optional[list] = None


@router.post("/anti-detect", response_model=AntiDetectResponse)
async def anti_detect(body: AntiDetectRequest):
    """Analyze text for AI patterns and optionally rewrite to reduce AI traces.

    If the score is below 60, automatically rewrites the text.
    Supports custom fatigue word lists per request.
    """
    from inkflow.pipeline.anti_ai import (
        analyze_text, generate_learning_examples,
        build_anti_ai_prompt_section,
    )
    from inkflow.utils.llm_utils import call_llm

    custom_words = body.custom_words or []

    def _run():
        analysis = analyze_text(body.text, extra_words=custom_words)
        learning = generate_learning_examples(analysis, body.text)

        rewritten = None
        if analysis["score"] < 60:
            # Auto-rewrite
            prompt = f"""请对以下文本进行去 AI 化改写。

{build_anti_ai_prompt_section()}

## 检测到的问题
- AI味评分: {analysis['score']}/100 (低于60需要改写)
- 疲劳词: {', '.join(f'{w}({c}次)' for w, c in analysis['fatigue_words'][:10])}
- 禁用句式: {len(analysis['banned_patterns'])} 处

## 原文
{body.text}

请输出改写后的完整文本。保持情节、人物和风格不变，仅消除 AI 写作痕迹。"""

            rewritten = call_llm(prompt, role_name="writer", temperature=0.7,
                                max_tokens=8192, json_mode=False)

        return analysis, learning, rewritten

    try:
        analysis, learning, rewritten = await asyncio.to_thread(_run)
        return AntiDetectResponse(
            ok=True,
            score=analysis["score"],
            fatigue_words=[{"word": w, "count": c} for w, c in analysis["fatigue_words"]],
            banned_patterns=analysis["banned_patterns"],
            sentence_stats=analysis["sentence_stats"],
            dialogue_ratio=analysis["dialogue_ratio"],
            rewritten_text=rewritten,
            learning_examples=learning if learning else None,
        )
    except Exception as e:
        raise HTTPException(500, f"Anti-detect failed: {e}")


@router.get("/fatigue-words")
async def get_fatigue_words():
    """Get the current fatigue word list (built-in + custom)."""
    from inkflow.pipeline.anti_ai import FATIGUE_WORDS, _custom_fatigue_words
    return {
        "built_in": FATIGUE_WORDS,
        "custom": _custom_fatigue_words,
        "total": len(FATIGUE_WORDS) + len(_custom_fatigue_words),
    }
