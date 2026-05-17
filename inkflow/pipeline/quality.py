"""Quality assessment for chapter drafts.

Used by the Editor to provide structured feedback and pass/fail decisions.
"""

import json
from typing import Dict, Any, List

from inkflow.utils.llm_utils import call_llm, parse_json_response
from inkflow.memory.world_state import WorldState


QUALITY_CHECK_PROMPT = """你是一位专业的小说编辑。请审校以下章节，给出详细评估。

## 世界观
{world_setting}

## 已有角色
{characters}

## 最近章节摘要
{recent_summaries}

## 本章大纲
{outline}

## 本章正文
{chapter_text}

---

请从以下维度评估（每项 1-10 分），并给出是否通过的判定：

1. **风格一致性** (style_score): 与整体风格是否一致
2. **情节逻辑** (logic_score): 情节是否自洽，有无矛盾
3. **角色一致性** (character_score): 人物言行是否符合设定
4. **节奏把控** (pacing_score): 张弛是否得当
5. **对话质量** (dialogue_score): 对话是否自然生动
6. **描写质量** (description_score): 场景/心理/动作描写
7. **伏笔运用** (foreshadowing_score): 伏笔是否合理埋设/回收

输出合法 JSON（json object）：
{{
  "style_score": 8,
  "logic_score": 7,
  "character_score": 9,
  "pacing_score": 6,
  "dialogue_score": 8,
  "description_score": 7,
  "foreshadowing_score": 7,
  "total_score": 52,
  "pass": true,
  "issues": [
    {{"severity": "high/medium/low", "category": "逻辑/风格/角色/节奏/对话/描写", "description": "具体问题描述", "suggestion": "修改建议"}}
  ],
  "highlights": ["值得保留的亮点1", "亮点2"],
  "rewrite_instructions": "如果不通过，这里给出具体的重写指导"
}}"""


class QualityScorer:
    """Evaluates chapter quality and provides structured feedback."""

    PASS_THRESHOLD = 50  # Total score out of 70 to pass
    MAX_RETRIES = 10

    def __init__(self, role_name: str = "editor"):
        self.role_name = role_name

    def evaluate(self, chapter_text: str, outline: str,
                 world_state: WorldState) -> Dict[str, Any]:
        """Evaluate a chapter draft against the world state and outline."""
        return self.evaluate_with_code_context(chapter_text, outline, world_state, "")

    def evaluate_with_code_context(self, chapter_text: str, outline: str,
                                    world_state: WorldState,
                                    code_context: str = "") -> Dict[str, Any]:
        """Evaluate a chapter draft with optional code-level check context.

        When code_context is provided, it's injected into the prompt so the LLM
        can focus on creative quality rather than re-checking factual consistency.
        """
        # Build context
        chars = "\n".join(
            f"- {name}: {ch.description} ({ch.traits}) [{ch.status}]"
            for name, ch in world_state.characters.items()
        )
        recent = world_state.get_recent_summaries(n=3)
        recent_text = "\n".join(
            f"第{i+1}章: {s}" for i, s in enumerate(recent)
        ) if recent else "（新故事，无前文）"

        # Inject code check context if available
        code_section = ""
        if code_context:
            code_section = f"""
## 已有代码层检查结果
{code_context}

请重点关注以下创意质量维度（事实性问题已由代码层处理）：
"""

        prompt = QUALITY_CHECK_PROMPT.format(
            world_setting=world_state.world_setting or "（未设定）",
            characters=chars or "（无角色）",
            recent_summaries=recent_text,
            outline=outline or "（无大纲，自由创作）",
            chapter_text=chapter_text[:8000],  # Truncate for LLM context
        )

        # Insert code context before the scoring instructions
        if code_section:
            prompt = prompt.replace(
                "请从以下维度评估",
                f"{code_section}\n请从以下维度评估"
            )

        raw = call_llm(prompt, role_name=self.role_name, temperature=0.2)
        result = parse_json_response(raw)

        # Ensure required fields
        # If total_score is missing or 0, calculate from individual scores
        if not result.get("total_score"):
            score_keys = ["style_score", "logic_score", "character_score",
                          "pacing_score", "dialogue_score", "description_score",
                          "foreshadowing_score"]
            result["total_score"] = sum(result.get(k, 0) for k in score_keys)
        result.setdefault("pass", result["total_score"] >= self.PASS_THRESHOLD)
        result.setdefault("issues", [])
        result.setdefault("highlights", [])
        result.setdefault("rewrite_instructions", "")

        return result

    def build_rewrite_prompt(self, original_text: str, feedback: Dict[str, Any],
                             outline: str, world_state: WorldState) -> str:
        """Build a rewrite prompt incorporating Editor feedback."""
        issues_text = "\n".join(
            f"- [{i.get('severity', 'medium')}] {i.get('category', '')}: "
            f"{i.get('description', '')} → 建议: {i.get('suggestion', '')}"
            for i in feedback.get("issues", [])
        )

        chars = "\n".join(
            f"- {name}: {ch.description} ({ch.traits})"
            for name, ch in world_state.characters.items()
        )

        return f"""请根据编辑反馈重写以下章节。

## 世界观
{world_state.world_setting or '（未设定）'}

## 角色
{chars or '（无角色）'}

## 大纲
{outline or '（无大纲）'}

## 编辑反馈
{feedback.get('rewrite_instructions', '')}

## 需要修改的问题：
{issues_text}

## 亮点（请保留）：
{chr(10).join('- ' + h for h in feedback.get('highlights', []))}

## 原文
{original_text}

请输出完整的重写后的章节正文。保留亮点，修正问题。"""
