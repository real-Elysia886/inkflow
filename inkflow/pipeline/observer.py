"""Observer Agent - Extracts 9 types of facts from chapter text.

Split into 3 specialized agents to reduce LLM logic pressure and improve accuracy.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any

from inkflow.utils.llm_utils import call_llm, parse_json_response

# 1. Social & Biological facts
SOCIAL_PROMPT = """你是一位细致的小说观察者，专注于角色、关系和状态。
请从以下章节正文中提取相关事实，输出严格 JSON。

## 世界观
{world_setting}

## 章节正文
{chapter_text}

## 已有角色
{characters}

---

请提取以下事实（json object）：
{{
  "characters": {{
    "appeared": ["本章出场角色列表"],
    "status_changes": [
      {{"name": "角色名", "old_status": "原状态", "new_status": "新状态", "reason": "原因"}}
    ]
  }},
  "relationships": {{
    "new": [
      {{"char1": "角色A", "char2": "角色B", "type": "关系类型", "description": "描述"}}
    ],
    "changed": [
      {{"char1": "角色A", "char2": "角色B", "old_type": "旧关系", "new_type": "新关系", "reason": "变化原因"}}
    ]
  }},
  "emotions": [
    {{"character": "角色名", "emotion": "情绪", "intensity": 7, "trigger": "触发原因", "target": "指向对象"}}
  ],
  "physical_state": [
    {{"character": "角色名", "changes": "身体状态变化（受伤/突破/恢复等）", "details": "具体描述"}}
  ]
}}"""

# 2. Environment & Resource facts
ENVIRONMENT_PROMPT = """你是一位细致的小说观察者，专注于地点、资源和时间。
请从以下章节正文中提取相关事实，输出严格 JSON。

## 世界观
{world_setting}

## 章节正文
{chapter_text}

## 已有角色
{characters}

---

请提取以下事实（json object）：
{{
  "locations": {{
    "used": ["本章出现的地点"],
    "new": [
      {{"name": "新地点名", "description": "描述", "type": "类型"}}
    ]
  }},
  "resources": {{
    "acquired": [
      {{"name": "物品名", "owner": "获得者", "quantity": 1, "description": "描述"}}
    ],
    "lost": [
      {{"name": "物品名", "owner": "失去者", "reason": "丢失原因"}}
    ],
    "consumed": [
      {{"name": "物品名", "owner": "使用者", "reason": "消耗原因"}}
    ]
  }},
  "time": {{
    "time_desc": "时间描述（如：三天后/次日清晨）",
    "duration": "本章时间跨度",
    "sequence_notes": "时间顺序备注"
  }}
}}"""

# 3. Narrative & Truth facts
NARRATIVE_PROMPT = """你是一位细致的小说观察者，专注于信息揭示和伏笔。
请从以下章节正文中提取相关事实，输出严格 JSON。

## 世界观
{world_setting}

## 章节正文
{chapter_text}

## 已有角色
{characters}

---

请提取以下事实（json object）：
{{
  "information": {{
    "revealed": [
      {{"fact": "被揭示的信息", "known_by": ["知道的人"], "chapter": 0}}
    ],
    "learned": [
      {{"character": "角色名", "fact": "学到的信息", "source": "信息来源"}}
    ]
  }},
  "foreshadowing": {{
    "planted": ["新埋设的伏笔"],
    "resolved": ["本章回收的伏笔"]
  }}
}}"""


class Observer:
    """Extracts structured facts from chapter text using parallel specialized agents."""

    def __init__(self, role_name: str = "editor"):
        self.role_name = role_name

    def observe(self, chapter_text: str, world_state) -> Dict[str, Any]:
        """Extract 9 types of facts using 3 parallel LLM calls."""
        chars = "\n".join(
            f"- {name}: {ch.description} ({ch.traits}) [{ch.status}]"
            for name, ch in world_state.characters.items()
        )

        ctx = {
            "chapter_text": chapter_text[:8000],
            "characters": chars or "（无角色）",
            "world_setting": world_state.world_setting[:1000] or "（未设定）",
        }

        def call_agent(prompt_tmpl):
            try:
                raw = call_llm(prompt_tmpl.format(**ctx), role_name=self.role_name, temperature=0.2)
                return parse_json_response(raw)
            except Exception as e:
                print(f"Error in Observer agent call: {e}")
                return {}

        with ThreadPoolExecutor(max_workers=3) as executor:
            f1 = executor.submit(call_agent, SOCIAL_PROMPT)
            f2 = executor.submit(call_agent, ENVIRONMENT_PROMPT)
            f3 = executor.submit(call_agent, NARRATIVE_PROMPT)

            res1 = f1.result(timeout=180)
            res2 = f2.result(timeout=180)
            res3 = f3.result(timeout=180)

        # Merge results
        result = {**res1, **res2, **res3}

        # Ensure all 9 keys exist with proper defaults
        for key in ("characters", "locations", "resources", "relationships",
                     "emotions", "information", "foreshadowing", "time", "physical_state"):
            if key in ("emotions", "physical_state"):
                result.setdefault(key, [])
            else:
                result.setdefault(key, {})

        return result
