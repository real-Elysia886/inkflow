"""Chapter Pipeline - Redesigned with modular step-based architecture.

Speed modes:
- draft:  plan → write (2 LLM calls, fastest)
- fast:   plan → write → observer (3 LLM calls, no review)
- standard: plan → write → normalize → dual-audit → [rewrite] → observer (5-7 LLM calls)

Standard mode uses dual-layer auditing:
  Layer 1: Code-level checks (zero token) - character status, resources, foreshadowing, etc.
  Layer 2: LLM evaluation - creative quality assessment (style, logic, pacing, etc.)

NormalizerStep enforces word count (1500-3000 ±20%) with a single compress/expand LLM call.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, Any, Optional, Callable, List
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field, ConfigDict

from pathlib import Path

from inkflow.memory.world_state import WorldState
from inkflow.pipeline.quality import QualityScorer
from inkflow.pipeline.observer import Observer
from inkflow.pipeline.reflector import Reflector
from inkflow.pipeline.governance import InputGovernance
from inkflow.pipeline.anti_ai import build_anti_ai_prompt_section, analyze_text, generate_learning_examples, cleanup_dashes, check_dash_count
from inkflow.pipeline.outline_writer import OutlineWriter
from inkflow.pipeline.audit.auditor import DualLayerAuditor
from inkflow.utils.llm_utils import call_llm
from inkflow.rag.indexer import ChapterIndex
from inkflow.skill_engine.registry import SkillRegistry


class PipelineContext(BaseModel):
    """Holds state and shared resources for a single pipeline execution."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ws: WorldState
    chapter_number: int
    speed_mode: str = "standard"
    
    # Shared resources
    rag_index: Optional[ChapterIndex] = None
    agents: Dict[str, Any] = Field(default_factory=dict)
    components: Dict[str, Any] = Field(default_factory=dict)
    progress_callback: Optional[Callable] = None
    
    # Execution state
    plan: Dict[str, Any] = Field(default_factory=dict)
    composed_context: str = ""
    draft: str = ""
    final_text: str = ""
    evaluation: Dict[str, Any] = Field(default_factory=dict)
    observations: Dict[str, Any] = Field(default_factory=dict)
    prev_chapter_text: Optional[str] = None
    prev_observations: Optional[Dict[str, Any]] = None

    # Runtime trace (captured during execution for debugging)
    trace: Dict[str, Any] = Field(default_factory=dict)

    def progress(self, stage: str, msg: str):
        if self.progress_callback:
            self.progress_callback(stage, msg)


class PipelineStep(ABC):
    """Abstract base class for a single step in the chapter generation pipeline."""
    
    @abstractmethod
    def execute(self, ctx: PipelineContext):
        pass


class OutlineStep(PipelineStep):
    """Ensures the outline window is populated."""
    def execute(self, ctx: PipelineContext):
        window = ctx.ws.outline_window
        if window.needs_fill(ctx.ws.current_chapter):
            ctx.progress("outline", "补充大纲窗口...")
            ctx.components["outline_writer"].fill_window(ctx.ws, window)


class PlanStep(PipelineStep):
    """Generates the chapter plan, possibly in parallel with previous chapter analysis."""
    def execute(self, ctx: PipelineContext):
        if ctx.plan: # Plan already provided via argument
            return

        if ctx.prev_chapter_text:
            ctx.progress("plan+observer", "并行：制定计划 + 提取上章事实...")
            with ThreadPoolExecutor(max_workers=2) as executor:
                plan_future = executor.submit(self._get_plan, ctx)
                observer_future = executor.submit(
                    ctx.components["observer"].observe, ctx.prev_chapter_text, ctx.ws
                )
                ctx.plan = plan_future.result()
                ctx.prev_observations = observer_future.result()
            
            # Apply previous chapter observations
            if ctx.prev_observations and "_error" not in ctx.prev_observations:
                ctx.progress("reflector", "更新上章真相文件...")
                prev_ch = ctx.chapter_number - 1
                if prev_ch > 0:
                    ctx.components["reflector"].apply(ctx.ws, ctx.prev_observations, prev_ch)
        else:
            ctx.plan = self._get_plan(ctx)

    def _get_plan(self, ctx: PipelineContext) -> Dict[str, Any]:
        ctx.progress("plan", "制定创作计划...")
        if ctx.agents.get("strategist"):
            return ctx.agents["strategist"].execute(ctx.ws)
        if ctx.agents.get("prophet"):
            return ctx.agents["prophet"].execute(ctx.ws)
        return ctx.components["governance"].plan_chapter(ctx.ws, ctx.chapter_number)


class ComposeStep(PipelineStep):
    """Assembles the context for writing, including RAG retrieval."""
    def execute(self, ctx: PipelineContext):
        ctx.progress("compose", "编排上下文...")
        rag_chunks = None
        if ctx.rag_index and ctx.rag_index.get_stats().get("total_chunks", 0) > 0:
            query = " ".join([
                ctx.plan.get("chapter_goal", ""),
                *(ctx.plan.get("focus_characters") or []),
                *(ctx.plan.get("must_keep") or []),
            ])
            hits = ctx.rag_index.search(query, max_results=3, exclude_chapter=ctx.chapter_number)
            if hits:
                rag_chunks = [c.text for c in hits]
        ctx.composed_context = ctx.components["governance"].compose_context(ctx.ws, ctx.plan, rag_chunks)


class WriteStep(PipelineStep):
    """Generates the initial draft of the chapter."""
    def execute(self, ctx: PipelineContext):
        ctx.progress("writer", "撰写初稿...")
        if ctx.agents.get("writer"):
            ctx.progress("writer", "正在生成...")
            ctx.draft = ctx.agents["writer"].execute(ctx.ws, ctx.plan,
                                                      on_chunk=lambda c: ctx.progress("writer_stream", c))
            return

        anti_ai_section = build_anti_ai_prompt_section()
        style = ctx.ws.style_fingerprint
        style_section = ""
        if style.tone:
            style_section = f"""
## 文风要求
- 语气: {style.tone}
- 节奏: {style.rhythm}
- 对话风格: {style.dialogue_style}
- 描写风格: {style.description_style}
- 句式偏好: {style.sentence_patterns}
"""
            if style.key_phrases:
                style_section += f"- 标志性用词: {', '.join(style.key_phrases[:5])}\n"

        prompt = f"""你是一位专业的小说写手。请根据以下创作计划和上下文撰写章节正文。

{ctx.composed_context}

{style_section}
{anti_ai_section}

## 创作计划
- 核心目标: {ctx.plan.get('chapter_goal', '')}
- 情绪走向: {ctx.plan.get('emotional_direction', '')}
- 节奏: {ctx.plan.get('pacing', '保持')}
- 必须保留: {', '.join(ctx.plan.get('must_keep', []))}
- 必须避免: {', '.join(ctx.plan.get('must_avoid', []))}

请输出完整的章节正文（1500-3000字）。要求：
1. 开头引人入胜，结尾留悬念
2. 对话自然生动，符合角色身份
3. 用具体感官细节代替抽象形容
4. 句式长短交替，节奏有变化
5. 破折号（——）每章最多出现 4 次，优先用逗号、句号或换行替代；禁止"不是…而是…"句式
6. 伏笔自然埋设，不露痕迹
7. 严格遵守去 AI 味约束
8. 正文第一行写一个合适的章节标题，不要加 # 或第X章 前缀，标题后空一行再开始正文"""

        ctx.progress("writer", "正在生成...")

        # Save trace data
        ctx.trace["writer_prompt"] = prompt
        ctx.trace["composed_context"] = ctx.composed_context
        ctx.trace["plan"] = ctx.plan

        ctx.draft = call_llm(prompt, role_name="writer", temperature=0.8,
                             max_tokens=8192, json_mode=False,
                             on_chunk=lambda c: ctx.progress("writer_stream", c))

        # Post-process: remove excess dashes
        original_dashes = check_dash_count(ctx.draft)
        if original_dashes > 4:
            ctx.draft = cleanup_dashes(ctx.draft, max_dashes=4)
            cleaned_dashes = check_dash_count(ctx.draft)
            ctx.progress("writer", f"破折号清理: {original_dashes} → {cleaned_dashes}")

        ctx.trace["draft"] = ctx.draft


class NormalizerStep(PipelineStep):
    """Normalizes chapter character count to target range.

    If the draft exceeds the target range by 20%, triggers a single
    compress/expand LLM call. Skipped in draft/fast modes.
    """
    MIN_CHARS = 1500
    MAX_CHARS = 3000
    TOLERANCE = 0.20  # ±20%

    def execute(self, ctx: PipelineContext):
        if ctx.speed_mode in ("draft", "fast"):
            return

        char_count = len(ctx.draft)
        lower = int(self.MIN_CHARS * (1 - self.TOLERANCE))  # 1200
        upper = int(self.MAX_CHARS * (1 + self.TOLERANCE))  # 3600

        if lower <= char_count <= upper:
            return  # Within acceptable range

        if char_count < lower:
            ctx.progress("normalizer", f"字数不足 ({char_count}字)，扩展中...")
            instruction = f"当前章节仅 {char_count} 字，目标 {self.MIN_CHARS}-{self.MAX_CHARS} 字。请扩展正文，补充场景描写、心理活动或对话，使总字数达到 {self.MIN_CHARS} 字以上。保持情节和风格不变。"
        else:
            ctx.progress("normalizer", f"字数过多 ({char_count}字)，压缩中...")
            instruction = f"当前章节有 {char_count} 字，目标 {self.MIN_CHARS}-{self.MAX_CHARS} 字。请精简正文，去除冗余描写和重复对话，使总字数降到 {self.MAX_CHARS} 字以内。保持核心情节和亮点不变。"

        prompt = f"""请对以下章节正文进行字数调整。

## 调整要求
{instruction}

## 原文
{ctx.draft}

请输出调整后的完整章节正文。保留章节标题。"""

        ctx.draft = call_llm(prompt, role_name="writer", temperature=0.5,
                             max_tokens=8192, json_mode=False)

        new_count = len(ctx.draft)
        ctx.progress("normalizer", f"调整完成: {char_count} → {new_count} 字")


class ReviewStep(PipelineStep):
    """Handles quality review and the rewrite loop using dual-layer auditing."""
    def execute(self, ctx: PipelineContext):
        if ctx.speed_mode == "draft":
            ctx.final_text = ctx.draft
            ctx.evaluation = {"total_score": 0, "pass": True, "skipped": True, "mode": "draft"}
            ctx.progress("editor", "草稿模式，跳过审校")
            return

        if ctx.speed_mode == "fast":
            ai_analysis = analyze_text(ctx.draft)
            ctx.final_text = ctx.draft
            ctx.evaluation = {"total_score": 0, "pass": True, "anti_ai_score": ai_analysis["score"], "mode": "fast"}
            ctx.progress("editor", f"快速模式，AI味评分: {ai_analysis['score']}/100")
            return

        # Standard mode: Dual-Layer Audit + Rewrite Loop
        ctx.progress("editor", "双层审校中...")

        # Anti-AI analysis (shared across retries)
        ai_analysis = analyze_text(ctx.draft)
        ctx.progress("editor", f"AI 味评分: {ai_analysis['score']}/100")

        outline_text = ctx.plan.get("chapter_goal", "")
        auditor = ctx.components.get("auditor")
        quality = ctx.components["quality"]

        if auditor:
            # Dual-layer audit: code checks + LLM evaluation
            audit_report = auditor.audit(
                chapter_text=ctx.draft,
                outline=outline_text,
                world_state=ctx.ws,
                chapter_number=ctx.chapter_number,
                anti_ai_score=ai_analysis["score"],
            )
            evaluation = audit_report.to_dict()
            evaluation["anti_ai_score"] = ai_analysis["score"]
            evaluation["anti_ai_issues"] = ai_analysis["fatigue_words"][:5]
            learning_examples = generate_learning_examples(ai_analysis, ctx.draft)
            if learning_examples:
                evaluation["anti_ai_learning"] = learning_examples

            ctx.progress("editor", f"代码层: {audit_report.code_result.checks_passed}/{audit_report.code_result.checks_total} 通过 | "
                         f"LLM评分: {audit_report.llm_total_score}/70 | "
                         f"AI味: {audit_report.anti_ai_score}/100")

            if audit_report.passed:
                ctx.progress("editor", "双层审校通过")
                ctx.final_text = ctx.draft
                ctx.evaluation = evaluation
                return

            # Build rewrite instructions from audit report
            rewrite_instructions = audit_report.rewrite_instructions
        else:
            # Fallback: old single-layer evaluation
            if ctx.agents.get("editor"):
                evaluation = ctx.agents["editor"].execute(ctx.ws, ctx.draft, outline_text)
            else:
                evaluation = quality.evaluate(ctx.draft, outline_text, ctx.ws)

            evaluation["anti_ai_score"] = ai_analysis["score"]
            evaluation["anti_ai_issues"] = ai_analysis["fatigue_words"][:5]
            learning_examples = generate_learning_examples(ai_analysis, ctx.draft)
            if learning_examples:
                evaluation["anti_ai_learning"] = learning_examples

            ctx.progress("editor", f"质量评分: {evaluation.get('total_score', 0)}/70")

            if evaluation.get("pass", False) and ai_analysis["score"] >= 60:
                ctx.progress("editor", "审校通过")
                ctx.final_text = ctx.draft
                ctx.evaluation = evaluation
                return

            rewrite_instructions = evaluation.get("rewrite_instructions", "")

        # Standard mode: single audit pass, let user decide on rewrite
        if ctx.speed_mode != "full_auto":
            ctx.final_text = ctx.draft
            ctx.evaluation = evaluation
            ctx.progress("editor", "审校完成，等待用户决定")
            return

        # Full auto mode: automatic rewrite loop (max 2 retries)
        max_rewrites = 2
        current_text = ctx.draft
        for retry in range(max_rewrites):
            ctx.progress("editor", f"第 {retry+1} 次重写...")
            rewrite_prompt = quality.build_rewrite_prompt(current_text, evaluation, outline_text, ctx.ws)

            # Add code-level fix instructions if available
            if rewrite_instructions:
                rewrite_prompt += f"\n\n## 必须修复的问题\n{rewrite_instructions}"

            rewrite_prompt += f"\n\n{build_anti_ai_prompt_section()}"
            if ai_analysis["fatigue_words"]:
                rewrite_prompt += "\n\n## 上一稿中出现的高频词（务必替换）\n"
                for word, count in ai_analysis["fatigue_words"][:5]:
                    rewrite_prompt += f"- \"{word}\" 出现了 {count} 次\n"

            current_text = call_llm(rewrite_prompt, role_name="writer", temperature=0.7, max_tokens=8192, json_mode=False,
                                    on_chunk=lambda c: ctx.progress("writer_stream", c))

            # Post-process: remove excess dashes after rewrite
            dash_count = check_dash_count(current_text)
            if dash_count > 4:
                current_text = cleanup_dashes(current_text, max_dashes=4)

            # Re-audit the rewritten text
            ctx.progress("editor", f"第 {retry+1} 次重写审校...")
            ai_analysis = analyze_text(current_text)

            if auditor:
                audit_report = auditor.audit(
                    chapter_text=current_text,
                    outline=outline_text,
                    world_state=ctx.ws,
                    chapter_number=ctx.chapter_number,
                    anti_ai_score=ai_analysis["score"],
                )
                evaluation = audit_report.to_dict()
                evaluation["anti_ai_score"] = ai_analysis["score"]

                if audit_report.passed:
                    ctx.progress("editor", f"第 {retry+1} 次重写后通过")
                    ctx.final_text = current_text
                    ctx.evaluation = evaluation
                    return

                rewrite_instructions = audit_report.rewrite_instructions
            else:
                evaluation = quality.evaluate(current_text, outline_text, ctx.ws)
                evaluation["anti_ai_score"] = ai_analysis["score"]

                if evaluation.get("pass", False) and ai_analysis["score"] >= 60:
                    ctx.progress("editor", f"第 {retry+1} 次重写后通过")
                    ctx.final_text = current_text
                    ctx.evaluation = evaluation
                    return

                rewrite_instructions = evaluation.get("rewrite_instructions", "")

        ctx.progress("editor", "已达最大重写次数，接受当前版本")
        evaluation["accepted_with_warning"] = True
        ctx.final_text = current_text
        ctx.evaluation = evaluation


class ObserveReflectStep(PipelineStep):
    """Extracts facts from the generated chapter and updates the world state."""
    def execute(self, ctx: PipelineContext):
        ctx.progress("observer", "提取事实...")
        ctx.observations = ctx.components["observer"].observe(ctx.final_text, ctx.ws)
        ctx.progress("reflector", "更新真相文件...")
        ctx.components["reflector"].apply(ctx.ws, ctx.observations, ctx.chapter_number)


class LibrarianStep(PipelineStep):
    """Updates chapter metadata and manages the outline window."""
    def execute(self, ctx: PipelineContext):
        ctx.progress("librarian", "更新章节记录...")
        if ctx.agents.get("librarian"):
            ctx.agents["librarian"].execute(ctx.ws, ctx.final_text, ctx.chapter_number)
        else:
            chars_present = ctx.plan.get("focus_characters") or []
            ctx.ws.add_chapter_meta(
                chapter_number=ctx.chapter_number,
                summary=ctx.plan.get("chapter_goal", "")[:200],
                title=f"第{ctx.chapter_number}章",
                pov=chars_present[0] if chars_present else "",
                location="",
                mood=ctx.plan.get("emotional_direction", ""),
                word_count=len(ctx.final_text),
                key_events=[],
                characters_present=chars_present,
            )
            for sp_name in (ctx.plan.get("subplot_attention") or []):
                ctx.ws.subplot_board.advance(sp_name, ctx.chapter_number)

        # 将标题添加到 plan 中（不含"第X章"前缀，仅保留标题本身）
        # 从大纲中获取章节标题，如果没有则使用章节目标的前20字
        outline = ctx.ws.outline_window.get_outline(ctx.chapter_number)
        if outline and outline.chapter_goal:
            # 使用章节目标作为标题（截取前20字）
            ctx.plan["chapter_title"] = outline.chapter_goal[:20]
        else:
            ctx.plan["chapter_title"] = f"第{ctx.chapter_number}章"

        ctx.ws.outline_window.confirm(ctx.chapter_number)
        ctx.ws.outline_window.advance(ctx.chapter_number)
        
        if ctx.observations and "_error" not in ctx.observations:
            ctx.progress("outline", "调整后续大纲...")
            adjustments = ctx.components["outline_writer"].refine_outlines(
                ctx.ws, ctx.plan.get("chapter_goal", ""), ctx.observations, ctx.ws.outline_window
            )
            for adj in adjustments:
                ch = adj.get("chapter_number")
                updates = adj.get("updates", {})
                o = ctx.ws.outline_window.get_outline(ch)
                if o and updates:
                    for key, val in updates.items():
                        if hasattr(o, key) and val:
                            setattr(o, key, val)
        
        ctx.components["outline_writer"].fill_window(ctx.ws, ctx.ws.outline_window)
        ctx.progress("librarian", "记忆更新完成")


class ChapterPipeline:
    """Orchestrates chapter generation with modular step-based architecture."""

    def __init__(self, rag_index: ChapterIndex = None, skill_map: Dict[str, str] = None,
                 project_dir: Optional[Path] = None):
        # Persistent project-level index when project_dir is supplied;
        # falls back to an in-memory index for ad-hoc use (tests, REPL).
        if rag_index is not None:
            self.rag_index = rag_index
        elif project_dir is not None:
            self.rag_index = ChapterIndex(db_path=Path(project_dir) / "rag_index.sqlite")
        else:
            self.rag_index = ChapterIndex()

        # Load agents first to resolve actual role names (distilled vs base)
        registry = SkillRegistry.get_default()
        self.agents = {}
        resolved_roles = {}
        for role in ("editor", "writer", "librarian", "strategist", "prophet"):
            slug = (skill_map or {}).get(role)
            if slug:
                info = registry.get(role, slug)
            else:
                info = registry.get_preferred(role)
            if info:
                self.agents[role] = info.instantiate()
                resolved_roles[role] = getattr(self.agents[role], 'role_name', role)
            else:
                resolved_roles[role] = role

        # Create internal components with resolved role names
        quality = QualityScorer(role_name=resolved_roles["editor"])
        self.components = {
            "quality": quality,
            "auditor": DualLayerAuditor(quality_scorer=quality, role_name=resolved_roles["editor"]),
            "observer": Observer(role_name=resolved_roles["editor"]),
            "reflector": Reflector(),
            "governance": InputGovernance(role_name=resolved_roles["strategist"]),
            "outline_writer": OutlineWriter(role_name=resolved_roles["strategist"])
        }
        self._progress_cb: Optional[Callable] = None
        self._cancelled: bool = False
        self._steps: List[PipelineStep] = [
            OutlineStep(),
            PlanStep(),
            ComposeStep(),
            WriteStep(),
            NormalizerStep(),
            ReviewStep(),
            ObserveReflectStep(),
            LibrarianStep()
        ]

    def on_progress(self, callback: Callable[[str, str], None]):
        self._progress_cb = callback

    def set_job_context(self, job_id: str, project_dir: Path):
        self._job_id = job_id
        self._project_dir = project_dir

    def cancel(self):
        """Request cancellation of the pipeline."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def _save_checkpoint(self, stage: str, msg: str, data: Dict = None):
        if not hasattr(self, "_project_dir") or not self._project_dir:
            return
        cp_dir = self._project_dir / "checkpoints"
        cp_dir.mkdir(exist_ok=True)
        cp_file = cp_dir / f"job_{self._job_id}.json"

        try:
            if cp_file.exists():
                cp_data = json.loads(cp_file.read_text(encoding="utf-8"))
            else:
                cp_data = {"history": [], "created_at": str(datetime.now())}

            cp_data["last_stage"] = stage
            cp_data["last_message"] = msg
            cp_data["history"].append({"stage": stage, "message": msg, "time": str(datetime.now())})
            if data:
                cp_data["data"] = data

            cp_file.write_text(json.dumps(cp_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[Pipeline] Checkpoint save failed: {e}")

    def _save_trace(self, ctx: PipelineContext):
        """Save runtime trace artifacts for debugging and analysis."""
        if not hasattr(self, "_project_dir") or not self._project_dir:
            return

        trace_dir = self._project_dir / "traces" / f"ch{ctx.chapter_number:03d}"
        trace_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Intent (from plan)
            intent_text = f"# 第{ctx.chapter_number}章创作意图\n\n"
            intent_text += f"- 核心目标: {ctx.plan.get('chapter_goal', '')}\n"
            intent_text += f"- 情绪走向: {ctx.plan.get('emotional_direction', '')}\n"
            intent_text += f"- 节奏: {ctx.plan.get('pacing', '')}\n"
            intent_text += f"- 关注角色: {', '.join(ctx.plan.get('focus_characters', []))}\n"
            intent_text += f"- 必须保留: {', '.join(ctx.plan.get('must_keep', []))}\n"
            intent_text += f"- 必须避免: {', '.join(ctx.plan.get('must_avoid', []))}\n"
            (trace_dir / "intent.md").write_text(intent_text, encoding="utf-8")

            # Context
            context_data = {
                "composed_context": ctx.trace.get("composed_context", ctx.composed_context),
                "plan": ctx.plan,
                "speed_mode": ctx.speed_mode,
                "chapter_number": ctx.chapter_number,
            }
            (trace_dir / "context.json").write_text(
                json.dumps(context_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # Writer prompt
            writer_prompt = ctx.trace.get("writer_prompt", "")
            if writer_prompt:
                (trace_dir / "prompt.txt").write_text(writer_prompt, encoding="utf-8")

            # Draft (LLM raw output)
            draft = ctx.trace.get("draft", ctx.draft)
            if draft:
                (trace_dir / "draft.txt").write_text(draft, encoding="utf-8")

            # Audit report
            audit_data = {
                "evaluation": ctx.evaluation,
                "passed": ctx.evaluation.get("pass", False),
                "anti_ai_score": ctx.evaluation.get("anti_ai_score", 0),
                "retries": 0 if ctx.final_text == ctx.draft else (
                    QualityScorer.MAX_RETRIES if ctx.evaluation.get("accepted_with_warning") else 1
                ),
            }
            (trace_dir / "audit.json").write_text(
                json.dumps(audit_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # Observations
            if ctx.observations:
                (trace_dir / "observations.json").write_text(
                    json.dumps(ctx.observations, ensure_ascii=False, indent=2), encoding="utf-8"
                )

        except Exception as e:
            print(f"[Pipeline] Failed to save trace: {e}")

    def generate_chapter(
        self,
        world_state: WorldState,
        outline: Optional[Dict[str, Any]] = None,
        speed_mode: str = "standard",
        prev_chapter_text: str = None,
    ) -> Dict[str, Any]:
        """Run full pipeline (all steps) and return result."""
        ctx = self._create_context(world_state, outline, speed_mode, prev_chapter_text)

        for step in self._steps:
            if self._cancelled:
                ctx.progress("cancelled", "任务已取消")
                break
            step.execute(ctx)
            self._maybe_save_checkpoint(ctx, step)

        result = self._build_result(ctx)
        result["cancelled"] = self._cancelled
        return result

    def generate_chapter_preview(
        self,
        world_state: WorldState,
        outline: Optional[Dict[str, Any]] = None,
        speed_mode: str = "standard",
        prev_chapter_text: str = None,
    ) -> Dict[str, Any]:
        """Run pipeline up to ReviewStep (steps 1-6), pause for human review.

        Does NOT run ObserveReflectStep or LibrarianStep.
        Does NOT save world state or chapter.
        """
        ctx = self._create_context(world_state, outline, speed_mode, prev_chapter_text)

        # Run steps 1-6 (Outline → Plan → Compose → Write → Normalize → Review)
        preview_steps = self._steps[:6]
        for step in preview_steps:
            if self._cancelled:
                ctx.progress("cancelled", "任务已取消")
                break
            step.execute(ctx)
            self._maybe_save_checkpoint(ctx, step)

        result = self._build_result(ctx)
        result["cancelled"] = self._cancelled
        return result

    def _maybe_save_checkpoint(self, ctx: PipelineContext, step: PipelineStep):
        """Save checkpoint with draft/final_text for key steps."""
        if isinstance(step, WriteStep) and ctx.draft:
            self._save_checkpoint("writer", "初稿完成", {"draft": ctx.draft})
        elif isinstance(step, NormalizerStep) and ctx.draft:
            self._save_checkpoint("normalizer", "标准化完成", {"draft": ctx.draft})
        elif isinstance(step, ReviewStep) and ctx.final_text:
            self._save_checkpoint("review", "审校完成", {"final_text": ctx.final_text})

    def confirm_chapter(
        self,
        world_state: WorldState,
        chapter_number: int,
        final_text: str,
        plan: Dict[str, Any],
        evaluation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run post-review steps (ObserveReflect + Librarian) with confirmed text.

        Called after human review approves the chapter.
        """
        def wrapped_progress(stage: str, msg: str):
            if self._progress_cb:
                self._progress_cb(stage, msg)

        ctx = PipelineContext(
            ws=world_state,
            chapter_number=chapter_number,
            speed_mode="standard",
            rag_index=self.rag_index,
            agents=self.agents,
            components=self.components,
            progress_callback=wrapped_progress,
            plan=plan,
            final_text=final_text,
            draft=final_text,
            evaluation=evaluation,
        )

        # Run steps 7-8 (ObserveReflect → Librarian)
        ObserveReflectStep().execute(ctx)
        LibrarianStep().execute(ctx)

        ctx.progress("done", "章节确认完成")
        self._save_trace(ctx)

        return self._build_result(ctx)

    def _create_context(
        self,
        world_state: WorldState,
        outline: Optional[Dict[str, Any]],
        speed_mode: str,
        prev_chapter_text: str,
    ) -> PipelineContext:
        """Create pipeline context and index previous chapter."""
        if prev_chapter_text and self.rag_index:
            prev_ch = world_state.current_chapter
            if prev_ch > 0:
                self.rag_index.add_chapter(prev_ch, prev_chapter_text)
                self.rag_index.commit()

        def wrapped_progress(stage: str, msg: str):
            if self._progress_cb:
                self._progress_cb(stage, msg)
            if hasattr(self, "_job_id"):
                self._save_checkpoint(stage, msg)

        return PipelineContext(
            ws=world_state,
            chapter_number=world_state.current_chapter + 1,
            speed_mode=speed_mode,
            rag_index=self.rag_index,
            agents=self.agents,
            components=self.components,
            progress_callback=wrapped_progress,
            plan=outline or {},
            prev_chapter_text=prev_chapter_text,
        )

    def _build_result(self, ctx: PipelineContext) -> Dict[str, Any]:
        """Build result dict from pipeline context."""
        retries = 0
        if ctx.evaluation.get("accepted_with_warning"):
            retries = QualityScorer.MAX_RETRIES
        elif ctx.final_text != ctx.draft:
            retries = 1

        return {
            "chapter_number": ctx.chapter_number,
            "speed_mode": ctx.speed_mode,
            "plan": ctx.plan,
            "outline": ctx.plan,
            "draft": ctx.draft,
            "evaluation": ctx.evaluation,
            "observations": ctx.observations,
            "final_text": ctx.final_text,
            "passed": ctx.evaluation.get("pass", False),
            "retries": retries,
        }
