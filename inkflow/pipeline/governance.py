"""Input Governance - Separates control input from generation.

Inspired by inkos's plan/compose architecture:
- author_intent.md: Long-term direction (what the story should become)
- current_focus.md: Short-term focus (what to emphasize in next 1-3 chapters)
- plan: Compiles intent + focus + context into chapter-level goals
- compose: Selects relevant truth file excerpts for the Writer's context
"""

from typing import Dict, Any, List

from inkflow.memory.world_state import WorldState
from inkflow.utils.llm_utils import call_llm, parse_json_response


PLAN_PROMPT = """你是一位小说策划师。根据以下信息，为第{chapter_number}章制定创作计划。

## 长期作者意图
{author_intent}

## 当前关注点
{current_focus}

## 世界设定与核心规则
{world_setting}
{setting_templates}

## 角色
{characters}

## 活跃情节线
{active_threads}

## 待回收伏笔
{pending_foreshadowing}

## 最近章节摘要
{recent_summaries}

## 最近情绪走向
{mood_sequence}

## 已用桥段（避免重复）
{used_tropes}
{outline_context}
{narrative_strategy}
---

请输出本章创作计划 JSON（json object）：

{{
  "chapter_goal": "本章核心目标（一句话）",
  "must_keep": ["必须保留的元素1", "元素2"],
  "must_avoid": ["必须避免的元素1", "元素2"],
  "focus_characters": ["本章重点角色1", "角色2"],
  "emotional_direction": "本章情绪走向",
  "pacing": "节奏建议（加速/减速/保持）",
  "subplot_attention": ["需要推进的支线"],
  "foreshadowing_actions": {{
    "to_plant": ["新伏笔"],
    "to_resolve": ["要回收的伏笔"]
  }}
}}"""


COMPOSE_SYSTEM = """你是一位上下文编排师。你的任务是从真相文件中选择与本章最相关的信息，编排成精简的上下文。

规则：
1. 只选择与本章创作计划直接相关的信息
2. 优先选择最近发生的事和活跃的状态
3. 去除冗余，保留关键事实
4. 总字数控制在 8000 字以内"""


class InputGovernance:
    """Manages the plan → compose → write pipeline."""

    def __init__(self, role_name: str = "strategist"):
        self.role_name = role_name

    def plan_chapter(self, world_state: WorldState,
                     chapter_number: int) -> Dict[str, Any]:
        """Generate a chapter-level creative plan.

        Args:
            world_state: Current WorldState.
            chapter_number: Chapter to plan for.

        Returns:
            Plan dict with chapter_goal, must_keep, must_avoid, etc.
        """
        def format_char(name, ch):
            base = f"- {name}: {ch.description} ({ch.traits}) [{ch.status}]"
            if ch.tags:
                base += f"\n  标签: {', '.join(ch.tags)}"
            if ch.custom_settings:
                for k, v in ch.custom_settings.items():
                    base += f"\n  {k}: {v}"
            return base

        chars = "\n".join(
            format_char(name, ch)
            for name, ch in world_state.characters.items()
        )

        templates = "\n".join(
            f"- {k}: {v}" for k, v in world_state.setting_templates.items()
        ) or "（未设定特殊规则）"

        threads = "\n".join(
            f"- [{t.thread_type}] {t.name}: {t.description}"
            for t in world_state.get_active_plot_threads()
        ) or "（无线程）"

        pending_fs = "\n".join(
            f"- {f.detail}（第{f.planted_chapter or '?'}章）"
            for f in world_state.get_pending_foreshadowing()
        ) or "（无待回收伏笔）"

        recent = world_state.get_recent_summaries(n=3)
        recent_text = "\n".join(
            f"第{i+1}章: {s}" for i, s in enumerate(recent)
        ) if recent else "（新故事）"

        mood_seq = world_state.get_mood_sequence(n=3)
        mood_text = " → ".join(mood_seq) if mood_seq else "（无记录）"

        tropes = "、".join(world_state.used_tropes[-10:]) if world_state.used_tropes else "（无）"

        # Outline window context
        if hasattr(world_state, "outline_window") and world_state.outline_window:
            outline = world_state.outline_window.get_outline(chapter_number)
            if outline:
                outline_context = f"""

## 大纲窗口（本章预定方向）
- 目标: {outline.chapter_goal}
- 核心冲突: {outline.core_conflict}
- 角色弧: {', '.join(outline.character_arcs) if outline.character_arcs else '（无）'}
- 关键事件: {', '.join(outline.key_events) if outline.key_events else '（无）'}
- 情绪走向: {outline.emotional_direction}
- 状态: {outline.status}
{"**注意：此大纲已确认，必须遵守。**" if outline.is_confirmed() else "（此大纲为草案，可适当调整）"}"""
            else:
                outline_context = ""
        else:
            outline_context = ""

        # Narrative strategy profile injection
        narrative_strategy = ""
        if world_state.narrative_profile and not world_state.narrative_profile.is_empty():
            narrative_strategy = "\n" + world_state.narrative_profile.to_prompt_section()

        prompt = PLAN_PROMPT.format(
            chapter_number=chapter_number,
            author_intent=world_state.author_intent or "（未设定）",
            current_focus=world_state.current_focus or "（未设定）",
            world_setting=world_state.world_setting[:500] or "（未设定）",
            setting_templates=templates,
            characters=chars or "（无角色）",
            active_threads=threads,
            pending_foreshadowing=pending_fs,
            recent_summaries=recent_text,
            mood_sequence=mood_text,
            used_tropes=tropes,
            outline_context=outline_context,
            narrative_strategy=narrative_strategy,
        )

        raw = call_llm(prompt, role_name=self.role_name, temperature=0.4)
        return parse_json_response(raw)

    def compose_context(self, world_state: WorldState,
                        plan: Dict[str, Any],
                        rag_chunks: List[str] = None) -> str:
        """Compose a focused context for the Writer.

        Selects relevant truth file excerpts based on the plan.

        Args:
            world_state: Current WorldState.
            plan: Chapter plan from plan_chapter().
            rag_chunks: Optional RAG-retrieved relevant chunks.

        Returns:
            Composed context string (≤2000 chars).
        """
        sections = []

        # Author intent + focus
        if world_state.author_intent:
            sections.append(f"## 长期方向\n{world_state.author_intent}")
        if world_state.current_focus:
            sections.append(f"## 当前关注\n{world_state.current_focus}")

        # Setting templates (Global rules)
        if world_state.setting_templates:
            rules = "\n".join(f"- {k}: {v}" for k, v in world_state.setting_templates.items())
            sections.append(f"## 世界设定核心规则\n{rules}")

        # Chapter goal from plan
        sections.append(f"## 本章目标\n{plan.get('chapter_goal', '')}")

        # Must keep/avoid
        must_keep = plan.get("must_keep") or []
        if must_keep:
            sections.append(f"## 必须保留\n" + "\n".join(f"- {k}" for k in must_keep))
        must_avoid = plan.get("must_avoid") or []
        if must_avoid:
            sections.append(f"## 必须避免\n" + "\n".join(f"- {a}" for a in must_avoid))

        # Focus characters
        focus_chars = plan.get("focus_characters") or []
        if focus_chars:
            char_details = []
            for name in focus_chars:
                ch = world_state.get_character(name)
                if ch:
                    rels = world_state.get_relationships(name)
                    rel_text = ", ".join(f"{r.char2}({r.relation_type})" for r in rels[:3])
                    
                    recent_emo = ""
                    if hasattr(world_state, "emotional_arcs"):
                        arc = world_state.emotional_arcs.get_arc(name)
                        if arc and arc.states:
                            recent_emo = f"，近期情绪: {arc.states[-1].emotion}"
                    
                    detail = f"- {name}: {ch.description} ({ch.traits})"
                    if ch.tags:
                        detail += f"\n  标签: {', '.join(ch.tags)}"
                    if ch.custom_settings:
                        for k, v in ch.custom_settings.items():
                            detail += f"\n  {k}: {v}"
                    
                    char_details.append(
                        f"{detail}"
                        f"{f'，关系: {rel_text}' if rel_text else ''}"
                        f"{recent_emo}"
                    )
            if char_details:
                sections.append(f"## 重点角色\n" + "\n".join(char_details))

        # Subplot attention
        subplot_names = plan.get("subplot_attention") or []
        if subplot_names and hasattr(world_state, "subplot_board") and world_state.subplot_board:
            subplot_details = []
            for sp in world_state.subplot_board.subplots:
                if sp.name in subplot_names:
                    subplot_details.append(f"- {sp.name} ({sp.subplot_type}): {sp.summary}")
            if subplot_details:
                sections.append(f"## 需推进的支线\n" + "\n".join(subplot_details))

        # RAG-retrieved relevant chunks
        if rag_chunks:
            sections.append(f"## 相关历史片段\n" + "\n".join(f"- {c[:200]}" for c in rag_chunks[:3]))

        # Resource state for focus characters
        if focus_chars and hasattr(world_state, "resource_ledger") and world_state.resource_ledger:
            resources = []
            for name in focus_chars:
                items = world_state.resource_ledger.get_active(owner=name)
                if items:
                    items_text = ", ".join(f"{i.name}×{i.quantity}" for i in items[:5])
                    resources.append(f"- {name}: {items_text}")
            if resources:
                sections.append(f"## 持有物品\n" + "\n".join(resources))

        composed = "\n\n".join(sections)

        # Truncate to ~2000 chars
        if len(composed) > 2000:
            composed = composed[:2000] + "\n...（已截断）"

        return composed
