"""OutlineWriter — Rolling 5-chapter outline generator.

System-level agent that maintains a sliding window of chapter outlines,
ensuring cross-chapter narrative coherence.
"""

import json
from typing import Dict, Any, List, Optional

from inkflow.memory.world_state import WorldState
from inkflow.memory.outline_window import OutlineWindow, ChapterOutline
from inkflow.utils.llm_utils import call_llm, parse_json_response


OUTLINE_GENERATE_PROMPT = """你是一位资深小说大纲设计师。请为以下小说生成 {count} 个章节的大纲。

## 世界观
{world_setting}

## 角色
{characters}

## 长期方向
{author_intent}

## 当前关注
{current_focus}
{narrative_strategy}

## 已有大纲参考
{existing_outlines}

## 已有章节摘要
{recent_summaries}

## 活跃伏笔
{pending_foreshadowing}

## 活跃支线
{active_threads}

---

请为第 {start_ch} 章到第 {end_ch} 章生成大纲。每章大纲必须包含：
- chapter_goal: 本章核心目标（一句话）
- core_conflict: 核心冲突
- character_arcs: 本章推进的角色弧（列表）
- key_events: 关键事件（列表）
- info_release: 本章释放的信息（列表）
- foreshadowing_actions: {{"to_plant": ["新伏笔"], "to_resolve": ["要回收的伏笔"]}}
- emotional_direction: 情绪走向（如 tense/light/hopeful/melancholy/suspenseful）
- notes: 补充说明

要求：
1. 各章之间有清晰的因果链和递进关系
2. 情绪节奏张弛有度，不能连续三章都是同一基调
3. 伏笔埋设和回收要分散在不同章节
4. 角色弧要有起承转合，不能一章就完成转变
5. 信息释放要控制节奏，不能一章倒完所有设定

输出合法 JSON（json object）：
{{
  "outlines": [
    {{
      "chapter_number": {start_ch},
      "chapter_goal": "...",
      "core_conflict": "...",
      "character_arcs": ["角色1弧线", "角色2弧线"],
      "key_events": ["事件1", "事件2"],
      "info_release": ["信息1"],
      "foreshadowing_actions": {{"to_plant": ["伏笔1"], "to_resolve": ["伏笔2"]}},
      "emotional_direction": "tense",
      "notes": ""
    }},
    ...
  ]
}}"""


OUTLINE_REFINE_PROMPT = """你是一位资深小说大纲设计师。章节生成后，发现实际内容与原大纲有偏差。请根据实际情况调整后续大纲。

## 本章实际内容摘要
{actual_summary}

## 本章提取的事实
{observations}

## 原大纲窗口
{current_window}

## 世界观
{world_setting}

## 角色
{characters}
{narrative_strategy}

---

请调整后续大纲，确保与实际发展保持一致。只调整需要修改的章节，不需要全部重写。调整后的大纲仍需符合叙事结构策略。

输出合法 JSON（json object）：
{{
  "adjustments": [
    {{
      "chapter_number": 5,
      "reason": "调整原因",
      "updates": {{
        "chapter_goal": "新的目标（如有变化）",
        "core_conflict": "新的冲突（如有变化）",
        "key_events": ["调整后的事件"],
        "notes": "调整说明"
      }}
    }}
  ]
}}"""


class OutlineWriter:
    """Generates and maintains a rolling 5-chapter outline window."""

    def __init__(self, role_name: str = "strategist"):
        self.role_name = role_name

    def generate_outlines(
        self,
        world_state: WorldState,
        start_chapter: int,
        count: int = 5,
        existing_outlines: Optional[List[ChapterOutline]] = None,
    ) -> List[ChapterOutline]:
        """Generate outlines for the next `count` chapters starting from `start_chapter`."""
        chars = "\n".join(
            f"- {name}: {ch.description} ({ch.traits}) [{ch.status}]"
            for name, ch in world_state.characters.items()
        ) or "（无角色）"

        existing_text = ""
        if existing_outlines:
            existing_text = "\n".join(
                f"第{o.chapter_number}章 [{o.status}]: {o.chapter_goal}"
                for o in existing_outlines
            )
        if not existing_text:
            existing_text = "（无已有大纲）"

        recent = world_state.get_recent_summaries(5)
        recent_text = "\n".join(f"第{i+1}章: {s}" for i, s in enumerate(recent)) if recent else "（新故事）"

        pending_fs = "\n".join(
            f"- {f.detail}（第{f.planted_chapter or '?'}章）"
            for f in world_state.get_pending_foreshadowing()
        ) or "（无）"

        threads = "\n".join(
            f"- [{t.thread_type}] {t.name}: {t.description}"
            for t in world_state.get_active_plot_threads()
        ) or "（无线程）"

        # Narrative strategy profile injection
        narrative_strategy = ""
        if world_state.narrative_profile and not world_state.narrative_profile.is_empty():
            narrative_strategy = "\n" + world_state.narrative_profile.to_prompt_section()

        prompt = OUTLINE_GENERATE_PROMPT.format(
            count=count,
            world_setting=world_state.world_setting[:800] or "（未设定）",
            characters=chars,
            author_intent=world_state.author_intent or "（未设定）",
            current_focus=world_state.current_focus or "（未设定）",
            narrative_strategy=narrative_strategy,
            existing_outlines=existing_text,
            recent_summaries=recent_text,
            pending_foreshadowing=pending_fs,
            active_threads=threads,
            start_ch=start_chapter,
            end_ch=start_chapter + count - 1,
        )

        raw = call_llm(prompt, role_name=self.role_name, temperature=0.5)
        result = parse_json_response(raw)

        outlines = []
        for i, item in enumerate(result.get("outlines") or []):
            ch_num = item.get("chapter_number", 0)
            # 确保 chapter_number 有效，如果为 0 则使用 start_chapter + i
            if ch_num <= 0:
                ch_num = start_chapter + i
            co = ChapterOutline(chapter_number=ch_num, status="pending")
            co.chapter_goal = item.get("chapter_goal", "")
            co.core_conflict = item.get("core_conflict", "")
            co.character_arcs = item.get("character_arcs") or []
            co.key_events = item.get("key_events") or []
            co.info_release = item.get("info_release") or []
            co.foreshadowing_actions = item.get("foreshadowing_actions", {"to_plant": [], "to_resolve": []})
            co.emotional_direction = item.get("emotional_direction", "")
            co.notes = item.get("notes", "")
            outlines.append(co)

        return outlines

    def refine_outlines(
        self,
        world_state: WorldState,
        actual_summary: str,
        observations: Dict[str, Any],
        window: OutlineWindow,
    ) -> List[Dict[str, Any]]:
        """After chapter generation, refine future outlines based on actual content.

        Returns list of adjustment dicts.
        """
        chars = "\n".join(
            f"- {name}: {ch.description} ({ch.traits})"
            for name, ch in world_state.characters.items()
        ) or "（无角色）"

        window_text = "\n".join(
            f"第{o.chapter_number}章 [{o.status}]: {o.chapter_goal}"
            for o in window.get_all()
        ) or "（无大纲）"

        obs_text = json.dumps(observations, ensure_ascii=False, indent=2)
        if len(obs_text) > 3000:
            obs_text = obs_text[:3000] + "\n...(truncated)"

        # Narrative strategy profile injection
        narrative_strategy = ""
        if world_state.narrative_profile and not world_state.narrative_profile.is_empty():
            narrative_strategy = "\n" + world_state.narrative_profile.to_prompt_section()

        prompt = OUTLINE_REFINE_PROMPT.format(
            actual_summary=actual_summary[:500],
            observations=obs_text,
            current_window=window_text,
            world_setting=world_state.world_setting[:500] or "（未设定）",
            characters=chars,
            narrative_strategy=narrative_strategy,
        )

        raw = call_llm(prompt, role_name=self.role_name, temperature=0.3)
        result = parse_json_response(raw)
        return result.get("adjustments") or []

    def fill_window(self, world_state: WorldState, window: OutlineWindow) -> OutlineWindow:
        """Fill missing outlines in the window."""
        current = world_state.current_chapter
        missing = window.get_missing_chapters(current)
        if not missing:
            return window

        start_ch = missing[0]
        count = len(missing)
        existing = window.get_all()

        new_outlines = self.generate_outlines(
            world_state, start_ch, count, existing_outlines=existing
        )

        for o in new_outlines:
            window.set_outline(o)

        return window

    def cold_start(self, world_state: WorldState) -> OutlineWindow:
        """Generate initial outline window from scratch (no prior chapters)."""
        window = OutlineWindow()
        outlines = self.generate_outlines(world_state, start_chapter=1, count=5)
        for o in outlines:
            window.set_outline(o)
        return window
