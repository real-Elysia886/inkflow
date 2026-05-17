# inkflow/skills/writer/distilled-writer/agent.py
"""写手（蒸馏作品） Agent."""

from pathlib import Path
from typing import Dict, Any, Optional, Callable
from inkflow.core.base_skill import BaseSkill
from inkflow.memory.world_state import WorldState
from inkflow.utils.llm_utils import call_llm


class DistilledWriterAgent(BaseSkill):
    """写手（蒸馏作品） skill agent."""

    json_mode = False

    def __init__(self, skill_path: str = None):
        if skill_path is None:
            skill_path = str(Path(__file__).parent)
        super().__init__(skill_path, role_name="distilled-writer")

    def execute(self, world_state: WorldState, outline: Dict[str, Any] = None,
                on_chunk: Optional[Callable] = None, **kwargs) -> str:
        context = self._build_context(world_state, outline=outline, **kwargs)

        messages = [
            {"role": "system", "content": self.system_prompt},
        ]

        if self.few_shots:
            for shot in self.few_shots:
                messages.append({"role": "user", "content": shot.get("input_context", "")})
                messages.append({"role": "assistant", "content": str(shot.get("output", ""))})

        messages.append({"role": "user", "content": context})

        return call_llm(
            messages=messages,
            role_name=self.role_name,
            temperature=self.model_params["temperature"],
            max_tokens=self.model_params["max_tokens"],
            json_mode=False,
            on_chunk=on_chunk,
        )

    def _build_context(self, world: WorldState, **kwargs) -> str:
        outline = kwargs.get("outline", {})
        recent = world.get_recent_summaries(n=5)
        idx_start = world.current_chapter - len(recent) + 1 if recent else 1
        recent_text = "\n".join(
            f"第{idx_start + i}章摘要: {s}" for i, s in enumerate(recent)
        ) if recent else "（新故事，无前文）"

        char_descriptions = "\n".join(
            f"- {name}: {info.description} ({getattr(info, 'traits', '')})"
            for name, info in world.characters.items()
        )

        # Outline details
        outline_text = ""
        if outline:
            chapter_goal = outline.get("chapter_goal", outline.get("chapter_summary", ""))
            key_events = outline.get("key_events", outline.get("must_keep", []))
            emotional = outline.get("emotional_direction", "")
            must_keep = outline.get("must_keep", [])
            must_avoid = outline.get("must_avoid", [])
            focus_chars = outline.get("focus_characters", [])
            outline_text = f"""
【本章大纲】
目标: {chapter_goal}
情绪走向: {emotional}
关键事件: {', '.join(key_events) if key_events else '（无）'}
必须保留: {', '.join(must_keep) if must_keep else '（无）'}
必须避免: {', '.join(must_avoid) if must_avoid else '（无）'}
重点角色: {', '.join(focus_chars) if focus_chars else '（无）'}
"""

        return f"""【世界观设定】
{world.world_setting or '（未设定）'}

【角色档案】
{char_descriptions or '（无角色）'}

【近期剧情回顾】
{recent_text}
{outline_text}
请开始创作本章正文。正文第一行写一个合适的章节标题，不要加"# "或"第X章"前缀，标题后空一行再开始正文。
"""
