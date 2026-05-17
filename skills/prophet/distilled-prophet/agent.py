# inkflow/skills/prophet/distilled-prophet/agent.py
"""大纲师（蒸馏作品） Agent."""

from pathlib import Path
from typing import Dict, Any
from inkflow.core.base_skill import BaseSkill
from inkflow.memory.world_state import WorldState
from inkflow.utils.llm_utils import call_llm, parse_json_response


class DistilledProphetAgent(BaseSkill):
    """大纲师（蒸馏作品） skill agent."""

    def __init__(self, skill_path: str = None):
        if skill_path is None:
            skill_path = str(Path(__file__).parent)
        super().__init__(skill_path, role_name="distilled-prophet")

    def execute(self, world_state: WorldState, chapter_number: int = None, **kwargs) -> Dict[str, Any]:
        if chapter_number is None:
            chapter_number = getattr(world_state, 'current_chapter', 0) + 1
        context = self._build_context(world_state, chapter_number=chapter_number, **kwargs)

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
        chapter_number = kwargs.get("chapter_number", world.current_chapter + 1)
        recent = world.get_recent_summaries(n=5)
        idx_start = world.current_chapter - len(recent) + 1 if recent else 1
        recent_text = "\n".join(
            f"第{idx_start + i}章: {s}" for i, s in enumerate(recent)
        ) if recent else "（新故事）"

        chars_dict = {
            name: {"description": c.description, "traits": c.traits, "status": c.status}
            for name, c in world.characters.items()
        }

        import json
        return json.dumps({
            "target_chapter": chapter_number,
            "world_setting": world.world_setting or "（未设定）",
            "recent_summaries": recent_text,
            "characters": chars_dict,
        }, ensure_ascii=False, indent=2)
