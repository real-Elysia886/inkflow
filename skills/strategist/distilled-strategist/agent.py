# inkflow/skills/strategist/distilled-strategist/agent.py
"""策略师（蒸馏作品） Agent."""

from pathlib import Path
from typing import Dict, Any
from inkflow.core.base_skill import BaseSkill
from inkflow.memory.world_state import WorldState
from inkflow.utils.llm_utils import call_llm, parse_json_response


class DistilledStrategistAgent(BaseSkill):
    """策略师（蒸馏作品） skill agent."""

    def __init__(self, skill_path: str = None):
        if skill_path is None:
            skill_path = str(Path(__file__).parent)
        super().__init__(skill_path, role_name="distilled-strategist")

    def execute(self, world_state: WorldState, **kwargs) -> Dict[str, Any]:
        context = self._build_context(world_state, **kwargs)

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
        chapter_number = world.current_chapter + 1
        recent = world.get_recent_summaries(n=3)
        idx_start = world.current_chapter - len(recent) + 1 if recent else 1
        recent_text = "\n".join(
            f"第{idx_start + i}章: {s}" for i, s in enumerate(recent)
        ) if recent else "（新故事）"

        pending = [f.detail for f in world.foreshadowing_pool if f.status == "pending"]
        active_subplots = [t.name for t in getattr(world, "plot_threads", []) if t.status == "active"]

        return f"""当前章节: 第{chapter_number}章
世界观: {world.world_setting or '（未设定）'}
作者意图: {getattr(world, 'author_intent', '')}
当前焦点: {getattr(world, 'current_focus', '')}

近期摘要:
{recent_text}

活跃支线: {', '.join(active_subplots) if active_subplots else '（无）'}
待回收伏笔: {', '.join(pending[:5]) if pending else '（无）'}

请为第{chapter_number}章制定创作策略，输出结构化 JSON。
"""
