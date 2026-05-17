import json
from typing import Dict, Any
from inkflow.core.base_skill import BaseSkill
from inkflow.utils.llm_utils import call_llm, parse_json_response

class ProphetAgent(BaseSkill):
    """大纲师：生成章节详细大纲与伏笔预设"""

    def __init__(self, skill_path: str):
        super().__init__(skill_path, role_name="prophet")

    def execute(self, world_state: Any, chapter_number: int = None, **kwargs) -> Dict[str, Any]:
        if chapter_number is None:
            chapter_number = getattr(world_state, 'current_chapter', 0) + 1
        context = self._build_context(world_state, chapter_number)
        
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
            json_mode=True
        )
        return parse_json_response(raw)

    def _build_context(self, memory_bank: Any, chapter_number: int) -> str:
        # 兼容 dict 和 WorldState 对象
        if hasattr(memory_bank, "world_setting"):
            world_setting = memory_bank.world_setting
            recent_summaries = memory_bank.get_recent_summaries(5)
            characters = memory_bank.characters
        else:
            world_setting = memory_bank.get("world_setting", "")
            recent_summaries = memory_bank.get("chapter_summaries", [])[-5:]
            characters = memory_bank.get("characters", {})

        # Convert Character objects to dict if needed
        if hasattr(memory_bank, "characters"):
            chars_dict = {name: {"description": c.description, "traits": c.traits, "status": c.status}
                         for name, c in memory_bank.characters.items()}
        else:
            chars_dict = characters

        return json.dumps({
            "target_chapter": chapter_number,
            "world_setting": world_setting,
            "recent_summaries": recent_summaries,
            "characters": chars_dict
        }, ensure_ascii=False, indent=2)
