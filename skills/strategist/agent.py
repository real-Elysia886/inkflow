import json
from typing import Dict, Any
from inkflow.core.base_skill import BaseSkill
from inkflow.memory.world_state import WorldState
from inkflow.utils.llm_utils import call_llm, parse_json_response


class StrategistAgent(BaseSkill):
    """战略师：叙事节奏规划与情节走向决策"""

    def __init__(self, skill_path: str):
        super().__init__(skill_path, role_name="strategist")
        if self.few_shots is None:
            self.few_shots = []

    def execute(self, world_state: WorldState, **kwargs) -> Dict[str, Any]:
        context = self._build_context(world_state)
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

    def _build_context(self, world_state: WorldState) -> str:
        chapter_number = world_state.current_chapter + 1
        outline = world_state.outline_window.get_outline(chapter_number)

        pending = [
            f.detail for f in world_state.foreshadowing_pool
            if f.status == "pending"
        ]
        active_subplots = [
            t.name for t in getattr(world_state, "plot_threads", [])
            if t.status == "active"
        ]
        
        ctx = {
            "current_chapter": chapter_number,
            "recent_summaries": world_state.get_recent_summaries(3),
            "active_subplots": active_subplots,
            "pending_foreshadowing": pending,
            "author_intent": getattr(world_state, "author_intent", ""),
            "current_focus": getattr(world_state, "current_focus", ""),
        }

        if outline:
            ctx["outline_preset"] = {
                "goal": outline.chapter_goal,
                "conflict": outline.core_conflict,
                "events": outline.key_events,
                "mood": outline.emotional_direction,
                "is_confirmed": outline.is_confirmed()
            }

        return json.dumps(ctx, ensure_ascii=False, indent=2)
