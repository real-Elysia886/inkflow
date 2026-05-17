# inkflow/skills/librarian/distilled-librarian/agent.py
"""图书管理员（蒸馏作品） Agent."""

from pathlib import Path
from typing import Dict, Any
from inkflow.core.base_skill import BaseSkill
from inkflow.memory.world_state import WorldState
from inkflow.utils.llm_utils import call_llm, parse_json_response


class DistilledLibrarianAgent(BaseSkill):
    """图书管理员（蒸馏作品） skill agent."""

    def __init__(self, skill_path: str = None):
        if skill_path is None:
            skill_path = str(Path(__file__).parent)
        super().__init__(skill_path, role_name="distilled-librarian")

    def execute(self, world_state: WorldState, chapter_content: str = "",
                chapter_number: int = None, **kwargs) -> Dict[str, Any]:
        if chapter_number is None:
            chapter_number = getattr(world_state, 'current_chapter', 0)
        context = self._build_context(world_state, chapter_content=chapter_content, **kwargs)

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
        chapter_content = kwargs.get("chapter_content", "")
        pending_foreshadowings = []
        for idx, f in enumerate(world.foreshadowing_pool):
            if f.status == "pending":
                pending_foreshadowings.append({
                    "id": idx, "detail": f.detail,
                    "planted_chapter": f.planted_chapter or "未知"
                })

        char_info = {
            name: {"description": c.description, "traits": c.traits, "status": c.status}
            for name, c in world.characters.items()
        }

        import json
        return f"""已知角色:
{json.dumps(char_info, ensure_ascii=False, indent=2)}

当前未回收的伏笔:
{json.dumps(pending_foreshadowings, ensure_ascii=False, indent=2) if pending_foreshadowings else '（无）'}

本章正文（前5000字）:
{chapter_content[:5000] if chapter_content else '（未提供）'}

请提取章节摘要、更新角色状态、追踪伏笔变化。
"""
