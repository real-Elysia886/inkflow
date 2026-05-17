import json
from typing import Dict, Any
from inkflow.core.base_skill import BaseSkill
from inkflow.memory.world_state import WorldState
from inkflow.utils.llm_utils import call_llm, parse_json_response


class EditorAgent(BaseSkill):
    """编辑：章节质量评估与润色建议"""

    def __init__(self, skill_path: str):
        super().__init__(skill_path, role_name="editor")

    def execute(self, world_state: WorldState, chapter_text: str = "", outline: str = "", **kwargs) -> Dict[str, Any]:
        context = self._build_context(world_state, chapter_text, outline)
        messages = [{"role": "system", "content": self.system_prompt}]
        if self.few_shots:
            for shot in self.few_shots:
                messages.append({"role": "user", "content": json.dumps(shot["input"], ensure_ascii=False)})
                messages.append({"role": "assistant", "content": json.dumps(shot["output"], ensure_ascii=False)})
        messages.append({"role": "user", "content": context})

        raw = call_llm(
            messages=messages,
            role_name=self.role_name,
            temperature=self.model_params["temperature"],
            max_tokens=self.model_params["max_tokens"],
            json_mode=True,
        )
        return parse_json_response(raw)

    def _build_context(self, world_state: WorldState, chapter_text: str, outline: str) -> str:
        characters_text = "\n".join(
            f"- {name}: {info.description} ({getattr(info, 'traits', '')})"
            for name, info in world_state.characters.items()
        )
        return f"""【世界观】
{world_state.world_setting}

【角色设定】
{characters_text}

【近期摘要】
{chr(10).join(world_state.get_recent_summaries(3))}

【本章大纲】
{outline or "（未提供）"}

【待审章节】
{chapter_text[:8000]}
"""
