"""Skill Generator - Generates inkflow skills from book analysis."""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List

from inkflow.utils.llm_utils import call_llm, parse_json_response


GENERATE_WRITER_PROMPT = """你是一位专业的 AI 提示词工程师。根据以下书籍分析报告，生成一个「写手」Skill 的 system prompt。

书籍分析报告：
---
{analysis}
---

要求：
1. prompt 必须让 LLM 能模仿该书的写作风格进行创作
2. 包含具体的风格指令（语气、节奏、句式、修辞、对话风格）
3. 包含描写指导（环境、人物、动作、心理）
4. 包含该类型的通用写作规范
5. 用中文撰写

输出合法 JSON（json object）：
{{
  "prompt": "完整的 system prompt 内容（Markdown 格式）",
  "description": "一句话描述这个写手 Skill 的特色"
}}

重要约束：
- prompt 中必须包含 "json" 这个词（API 要求）
- 写手只负责写正文，不做结构规划
- 输出的是纯文本章节正文，不是 JSON"""


GENERATE_STRATEGIST_PROMPT = """你是一位专业的 AI 提示词工程师。根据以下书籍分析报告，生成一个「策略师」Skill 的 system prompt。

书籍分析报告：
---
{analysis}
---

要求：
1. prompt 必须让 LLM 能基于该书的世界观模式进行策略规划
2. 包含情节架构指导（冲突设计、转折手法、节奏把控）
3. 包含世界观构建规范（规则体系、力量体系）
4. 包含该类型的故事结构模板
5. 用中文撰写

输出合法 JSON（json object）：
{{
  "prompt": "完整的 system prompt 内容（Markdown 格式）",
  "description": "一句话描述这个策略师 Skill 的特色"
}}

重要约束：
- prompt 中必须包含 "json" 这个词（API 要求）
- 策略师只做结构规划，不写散文，不在输出中使用俚语/脏话
- 必须定义输出 JSON schema，包含 chapter_goal, must_keep, must_avoid, focus_characters, emotional_direction, pacing, foreshadowing_actions 字段"""


GENERATE_PROPHET_PROMPT = """你是一位专业的 AI 提示词工程师。根据以下书籍分析报告，生成一个「大纲师」Skill 的 system prompt。

书籍分析报告：
---
{analysis}
---

要求：
1. prompt 必须让 LLM 能基于该书的章节结构模式生成章纲
2. 包含章节结构指导（开头/发展/高潮/结尾）
3. 包含伏笔管理规范（埋设/回收技巧）
4. 包含角色引入和发展弧线指导
5. 用中文撰写

输出合法 JSON（json object）：
{{
  "prompt": "完整的 system prompt 内容（Markdown 格式）",
  "description": "一句话描述这个大纲师 Skill 的特色"
}}

重要约束：
- prompt 中必须包含 "json" 这个词（API 要求）
- 必须定义输出 JSON schema，包含 chapter_title, new_characters, key_events, foreshadowing, chapter_summary 字段"""


GENERATE_EDITOR_PROMPT = """你是一位专业的 AI 提示词工程师。根据以下书籍分析报告，生成一个「编辑」Skill 的 system prompt。

书籍分析报告：
---
{analysis}
---

要求：
1. prompt 必须让 LLM 能基于该书的风格标准进行审校
2. 包含语言质量检查标准（语法、用词、句式）
3. 包含风格一致性检查（是否符合原书风格）
4. 包含情节逻辑检查规范
5. 用中文撰写

输出合法 JSON（json object）：
{{
  "prompt": "完整的 system prompt 内容（Markdown 格式）",
  "description": "一句话描述这个编辑 Skill 的特色"
}}

重要约束：
- prompt 中必须包含 "json" 这个词（API 要求）
- 编辑只做审校评分，不做改写
- 必须定义输出 JSON schema，包含 total_score, pass, style_score, logic_score, character_score, pacing_score, dialogue_score, description_score, foreshadowing_score, issues, highlights, rewrite_instructions 字段
- 必须定义 pass 阈值（如 total_score >= 45 为 pass）"""


GENERATE_LIBRARIAN_PROMPT = """你是一位专业的 AI 提示词工程师。根据以下书籍分析报告，生成一个「图书管理员」Skill 的 system prompt。

书籍分析报告：
---
{analysis}
---

要求：
1. prompt 必须让 LLM 能基于该书的模式生成章节摘要
2. 包含摘要撰写规范（长度、重点、语言风格）
3. 包含角色状态追踪规范
4. 包含伏笔追踪规范
5. 用中文撰写

输出合法 JSON（json object）：
{{
  "prompt": "完整的 system prompt 内容（Markdown 格式）",
  "description": "一句话描述这个图书管理员 Skill 的特色"
}}

重要约束：
- prompt 中必须包含 "json" 这个词（API 要求）
- 必须定义输出 JSON schema，包含 chapter_summary, new_foreshadowings, resolved_foreshadowings, character_updates 字段
- 图书管理员做章节摘要+角色追踪+伏笔管理，不做全书分析"""


SAMPLE_TEMPLATES = {
    "editor": """根据书籍分析报告，为「编辑」Skill 生成 2 个 few-shot 样本。
编辑的任务是审校评分，不是改写。样本必须展示：输入一段文本 → 输出评分+问题+建议。

书籍分析报告：{analysis}

输出合法 JSON：
{{
  "samples": [
    {{
      "input_context": "【世界观】...\\n【角色】...\\n【待审章节】...\\n请审校以上章节。",
      "output": {{"total_score": 55, "pass": false, "style_score": 12, "logic_score": 10, "character_score": 8, "pacing_score": 7, "dialogue_score": 8, "description_score": 5, "foreshadowing_score": 5, "issues": ["问题1", "问题2"], "highlights": ["亮点1"], "rewrite_instructions": "修改建议..."}}
    }},
    {{
      "input_context": "【世界观】...\\n【角色】...\\n【待审章节】...\\n请审校以上章节。",
      "output": {{"total_score": 62, "pass": true, "style_score": 14, "logic_score": 12, "character_score": 10, "pacing_score": 8, "dialogue_score": 8, "description_score": 5, "foreshadowing_score": 5, "issues": [], "highlights": ["亮点1", "亮点2"], "rewrite_instructions": ""}}
    }}
  ]
}}""",

    "writer": """根据书籍分析报告，为「写手」Skill 生成 2 个 few-shot 样本。
写手的任务是根据大纲撰写章节正文。样本展示：输入大纲+设定 → 输出章节正文（纯文本）。

书籍分析报告：{analysis}

输出合法 JSON：
{{
  "samples": [
    {{
      "input_context": "【世界观】...\\n【角色】...\\n【本章大纲】目标: ...\\n请开始创作。",
      "output": "（章节正文纯文本，包含标题，800-1500字，展示该书的写作风格）"
    }},
    {{
      "input_context": "【世界观】...\\n【角色】...\\n【本章大纲】目标: ...\\n请开始创作。",
      "output": "（章节正文纯文本，包含标题，800-1500字，展示不同的场景类型）"
    }}
  ]
}}""",

    "strategist": """根据书籍分析报告，为「策略师」Skill 生成 2 个 few-shot 样本。
策略师的任务是结构规划，不是写散文。样本展示：输入当前状态 → 输出结构化策略 JSON。

书籍分析报告：{analysis}

输出合法 JSON：
{{
  "samples": [
    {{
      "input_context": "当前章节: 第N章\\n世界观: ...\\n近期摘要: ...\\n活跃支线: ...\\n待回收伏笔: ...",
      "output": {{"chapter_goal": "本章核心目标", "must_keep": ["必须保留1"], "must_avoid": ["必须避免1"], "focus_characters": ["角色1"], "emotional_direction": "情绪走向", "pacing": "节奏", "subplot_attention": "支线关注", "foreshadowing_actions": {{"to_plant": ["伏笔1"], "to_resolve": ["伏笔2"]}}}}
    }},
    {{
      "input_context": "当前章节: 第N章\\n世界观: ...\\n近期摘要: ...",
      "output": {{"chapter_goal": "...", "must_keep": [], "must_avoid": [], "focus_characters": [], "emotional_direction": "...", "pacing": "...", "subplot_attention": "...", "foreshadowing_actions": {{"to_plant": [], "to_resolve": []}}}}
    }}
  ]
}}""",

    "prophet": """根据书籍分析报告，为「大纲师」Skill 生成 2 个 few-shot 样本。
大纲师的任务是生成章节详细大纲。样本展示：输入目标章节信息 → 输出章节大纲 JSON。

书籍分析报告：{analysis}

输出合法 JSON：
{{
  "samples": [
    {{
      "input_context": "{{\"target_chapter\": N, \"world_setting\": \"...\", \"recent_summaries\": \"...\", \"characters\": {{...}}}}",
      "output": {{"chapter_title": "章节标题", "new_characters": [], "key_events": ["事件1", "事件2"], "foreshadowing": {{"to_plant": ["伏笔1"], "to_resolve": []}}, "chapter_summary": "章节摘要"}}
    }},
    {{
      "input_context": "{{\"target_chapter\": N, \"world_setting\": \"...\", \"recent_summaries\": \"...\", \"characters\": {{...}}}}",
      "output": {{"chapter_title": "...", "new_characters": [], "key_events": [], "foreshadowing": {{"to_plant": [], "to_resolve": []}}, "chapter_summary": "..."}}
    }}
  ]
}}""",

    "librarian": """根据书籍分析报告，为「图书管理员」Skill 生成 2 个 few-shot 样本。
图书管理员的任务是生成章节摘要+更新角色状态+追踪伏笔。样本展示：输入章节内容 → 输出摘要 JSON。

书籍分析报告：{analysis}

输出合法 JSON：
{{
  "samples": [
    {{
      "input_context": "已知角色: ...\\n当前未回收的伏笔: ...\\n本章正文: ...\\n请提取摘要。",
      "output": {{"chapter_summary": "第N章摘要", "new_foreshadowings": [{{"detail": "新伏笔", "type": "埋设"}}], "resolved_foreshadowings": [0], "character_updates": {{"角色名": "状态更新"}}}}
    }},
    {{
      "input_context": "已知角色: ...\\n当前未回收的伏笔: ...\\n本章正文: ...\\n请提取摘要。",
      "output": {{"chapter_summary": "...", "new_foreshadowings": [], "resolved_foreshadowings": [], "character_updates": {{}}}}
    }}
  ]
}}""",
}


class SkillGenerator:
    """Generates inkflow skills from book analysis results."""

    def __init__(self, role_name: str = "prophet", model_override=None):
        self.role_name = role_name
        self.model_override = model_override

    def generate_prompt(self, skill_type: str, analysis: Dict[str, Any]) -> Dict[str, str]:
        """Generate a system prompt for a specific skill type."""
        analysis_text = json.dumps(analysis, ensure_ascii=False, indent=2)
        if len(analysis_text) > 12000:
            analysis_text = analysis_text[:12000] + "\n... (truncated)"

        prompts = {
            "writer": GENERATE_WRITER_PROMPT,
            "strategist": GENERATE_STRATEGIST_PROMPT,
            "prophet": GENERATE_PROPHET_PROMPT,
            "editor": GENERATE_EDITOR_PROMPT,
            "librarian": GENERATE_LIBRARIAN_PROMPT,
        }

        prompt_template = prompts.get(skill_type)
        if not prompt_template:
            return {"error": f"Unknown skill type: {skill_type}"}

        raw = call_llm(prompt_template.format(analysis=analysis_text), role_name=self.role_name, temperature=0.5,
                       model_override=self.model_override)
        return parse_json_response(raw)

    def generate_samples(self, skill_type: str, analysis: Dict[str, Any]) -> List[Dict]:
        analysis_text = json.dumps(analysis, ensure_ascii=False, indent=2)
        if len(analysis_text) > 8000:
            analysis_text = analysis_text[:8000] + "\n... (truncated)"

        template = SAMPLE_TEMPLATES.get(skill_type)
        if not template:
            return []

        raw = call_llm(
            template.format(analysis=analysis_text),
            role_name=self.role_name,
            temperature=0.5,
            model_override=self.model_override,
        )
        result = parse_json_response(raw)
        return result.get("samples", [])

    def _generate_one_skill(self, st: str, analysis: Dict[str, Any]) -> tuple[str, Dict]:
        """Generate prompt + samples for a single skill type."""
        prompt_result = self.generate_prompt(st, analysis)
        samples = self.generate_samples(st, analysis)
        return st, {
            "prompt": prompt_result.get("prompt", ""),
            "description": prompt_result.get("description", ""),
            "samples": samples,
        }

    def generate_all_skills(
        self,
        analysis: Dict[str, Any],
        book_title: str = "distilled",
        progress_callback=None,
        skip: set = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Generate all 5 skills in parallel. Pass skip={skill_type,...} to resume."""
        skill_types = [s for s in ["writer", "strategist", "prophet", "editor", "librarian"]
                       if s not in (skip or set())]
        results = {}
        total = len(skill_types)
        completed = 0

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(self._generate_one_skill, st, analysis): st
                for st in skill_types
            }
            for future in as_completed(futures):
                st, data = future.result()
                results[st] = data
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, f"已完成 {st}")

        if progress_callback:
            progress_callback(total, total, "全部生成完成")

        return results


def build_skill_meta(
    skill_type: str,
    book_title: str,
    analysis: Dict[str, Any],
    generated: Dict[str, Any],
) -> Dict[str, Any]:
    """Build skill metadata from generated content."""
    from inkflow.skill_engine.skill_presets import get_skill_preset
    preset = get_skill_preset(skill_type)

    prompt_content = generated.get("prompt", "")
    # Replace "未知作品" placeholder with actual book title
    prompt_content = prompt_content.replace("未知作品", book_title).replace("《未知作品》", f"《{book_title}》")

    return {
        "skill_type": skill_type,
        "display_name": f"{preset['display_name']}（{book_title}）",
        "description": generated.get("description", preset["description"]),
        "provider": preset["default_provider"],
        "model": preset["default_model"],
        "temperature": preset["default_temperature"],
        "max_tokens": preset["default_max_tokens"],
        "prompt_content": prompt_content,
        "samples_content": generated.get("samples", []),
        "distilled_from": book_title,
        "analysis_summary": analysis.get("overall_style", ""),
    }
