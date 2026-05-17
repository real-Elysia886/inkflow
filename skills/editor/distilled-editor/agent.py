# inkflow/skills/editor/distilled-editor/agent.py
"""编辑（蒸馏作品） Agent."""

from pathlib import Path
from typing import Dict, Any
from inkflow.core.base_skill import BaseSkill
from inkflow.memory.world_state import WorldState
from inkflow.utils.llm_utils import call_llm, parse_json_response


class DistilledEditorAgent(BaseSkill):
    """编辑（蒸馏作品） skill agent."""

    def __init__(self, skill_path: str = None):
        if skill_path is None:
            skill_path = str(Path(__file__).parent)
        super().__init__(skill_path, role_name="distilled-editor")

    def execute(self, world_state: WorldState, chapter_text: str = "", outline: str = "", **kwargs) -> Dict[str, Any]:
        context = self._build_context(world_state, chapter_text=chapter_text, outline=outline, **kwargs)

        messages = [
            {"role": "system", "content": self.system_prompt},
        ]

        if self.few_shots:
            for shot in self.few_shots:
                messages.append({"role": "user", "content": shot.get("input_context", "")})
                messages.append({"role": "assistant", "content": str(shot.get("output", ""))})

        messages.append({"role": "user", "content": context})

        raw = call_llm(
            messages=messages,
            role_name=self.role_name,
            temperature=self.model_params["temperature"],
            max_tokens=self.model_params["max_tokens"],
            json_mode=True,
        )
        return parse_json_response(raw)

    def _build_context(self, world: WorldState, **kwargs) -> str:
        chapter_text = kwargs.get("chapter_text", "")
        outline = kwargs.get("outline", "")
        recent = world.get_recent_summaries(n=3)
        idx_start = world.current_chapter - len(recent) + 1 if recent else 1
        recent_text = "\n".join(
            f"第{idx_start + i}章: {s}" for i, s in enumerate(recent)
        ) if recent else "（新故事）"

        char_descriptions = "\n".join(
            f"- {name}: {info.description} ({getattr(info, 'traits', '')})"
            for name, info in world.characters.items()
        )

        return f"""【世界观】
{world.world_setting or '（未设定）'}

【角色设定】
{char_descriptions or '（无角色）'}

【近期摘要】
{recent_text}

【本章大纲】
{outline or '（未提供）'}

【待审章节】
{chapter_text[:8000]}

请对以上章节进行审校，输出评分、问题和修改建议。
"""
