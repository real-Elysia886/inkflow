"""Book Analyzer - Uses LLM to analyze writing style, structure, and patterns."""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional

from inkflow.utils.llm_utils import call_llm, parse_json_response


CHUNK_SIZE = 5000  # chars per analysis chunk
MAX_CHUNKS = 20    # max chunks to analyze


ANALYSIS_PROMPT = """你是一位专业的文学分析师。请从以下文本片段中提取创作特征，输出严格 JSON。

分析维度：
1. **writing_style**: 写作风格（语气、节奏、句式偏好、修辞手法、对话风格）
2. **world_building**: 世界观构建元素（设定类型、规则体系、环境描写特点）
3. **character_patterns**: 角色塑造模式（人物类型、性格刻画方式、对话特点、成长弧线）
4. **plot_structure**: 情节结构模式（冲突类型、节奏把控、转折手法、章节结构）
5. **foreshadowing**: 伏笔技巧（埋设方式、回收手法、悬念管理）
6. **narrative_structure**: 叙事结构模式（章节功能节奏、POV切换规律、伏笔密度与回收周期、多线编排方式、信息释放梯度、张力弧线、冲突升级阶梯、情绪节奏）

文本片段：
---
{chunk}
---

请输出合法 JSON（json object，不要输出其他内容）：
{{
  "writing_style": {{
    "tone": "...",
    "rhythm": "...",
    "sentence_patterns": "...",
    "rhetoric": "...",
    "dialogue_style": "..."
  }},
  "world_building": {{
    "genre": "...",
    "setting_type": "...",
    "rule_system": "...",
    "environment_desc": "..."
  }},
  "character_patterns": {{
    "archetypes": ["..."],
    "personality_methods": "...",
    "dialogue_traits": "...",
    "growth_arcs": "..."
  }},
  "plot_structure": {{
    "conflict_types": ["..."],
    "pacing": "...",
    "turning_points": "...",
    "chapter_structure": "..."
  }},
  "foreshadowing": {{
    "planting_methods": "...",
    "payoff_techniques": "...",
    "suspense_management": "..."
  }},
  "narrative_structure": {{
    "chapter_function_pattern": "每章的功能分布规律（刺激事件/纠葛/转折/高潮/收束）",
    "pov_pattern": "POV切换频率与规律",
    "foreshadowing_density": "伏笔密度与平均回收周期",
    "multiline_style": "多线叙事的编排方式（交替/并行/主副线比例）",
    "info_release": "信息释放梯度（每次释放的谜题量与解答节奏）",
    "tension_template": "张力弧线宏观走势",
    "conflict_escalation": "冲突升级阶梯",
    "emotional_rhythm": "情绪节奏模板",
    "chapter_structure": "单章内部结构模板（开头-发展-高潮-结尾的比例）"
  }}
}}"""


SYNTHESIS_PROMPT = """你是一位专业的文学分析师。请将以下多个文本片段的分析结果综合为一份统一的创作特征报告。

各片段分析结果：
---
{analyses}
---

请输出一份综合报告 JSON（json object，不要输出其他内容），格式如下：
{{
  "book_title": "（从内容推断的书名或'未知作品'）",
  "genre": "（类型，如玄幻/都市/科幻/言情等）",
  "overall_style": "（一段话概括整体写作风格）",
  "writing_style": {{
    "tone": "综合语气特征",
    "rhythm": "节奏特点",
    "sentence_patterns": "句式偏好",
    "rhetoric": "常用修辞",
    "dialogue_style": "对话风格",
    "description_style": "描写风格",
    "key_phrases": ["标志性用词/句式1", "标志性用词/句式2"]
  }},
  "world_building": {{
    "genre": "类型",
    "setting_type": "设定类型",
    "rule_system": "规则体系描述",
    "environment_desc": "环境描写特点",
    "power_system": "力量体系（如有）"
  }},
  "character_patterns": {{
    "archetypes": ["常见人物原型1", "常见人物原型2"],
    "personality_methods": "性格刻画手法",
    "dialogue_traits": "对话特点",
    "growth_arcs": "成长弧线模式",
    "relationship_dynamics": "人物关系模式"
  }},
  "plot_structure": {{
    "conflict_types": ["常见冲突类型"],
    "pacing": "节奏特点",
    "turning_points": "转折手法",
    "chapter_structure": "章节结构模式",
    "hook_techniques": "开篇/悬念技巧"
  }},
  "foreshadowing": {{
    "planting_methods": "伏笔埋设手法",
    "payoff_techniques": "伏笔回收技巧",
    "suspense_management": "悬念管理方式",
    "common_patterns": ["常见伏笔模式1", "常见伏笔模式2"]
  }},
  "narrative_structure": {{
    "chapter_function_pattern": "每章的功能分布规律（刺激事件/纠葛/转折/高潮/收束）",
    "pov_pattern": "POV切换频率与规律",
    "foreshadowing_density": "伏笔密度与平均回收周期",
    "multiline_style": "多线叙事的编排方式（交替/并行/主副线比例）",
    "info_release": "信息释放梯度（每次释放的谜题量与解答节奏）",
    "tension_template": "张力弧线宏观走势",
    "conflict_escalation": "冲突升级阶梯",
    "emotional_rhythm": "情绪节奏模板",
    "chapter_structure": "单章内部结构模板（开头-发展-高潮-结尾的比例）"
  }},
  "sample_passages": [
    "（从原文中摘录 2-3 段最能代表风格的片段，每段 100-200 字）"
  ]
}}"""


def split_book(text: str, chunk_size: int = CHUNK_SIZE, max_chunks: int = MAX_CHUNKS) -> List[str]:
    """Split book text into analysis-friendly chunks.

    Tries to split at paragraph boundaries. Returns at most max_chunks.
    """
    # Clean up whitespace
    text = text.strip()
    if not text:
        return []

    # Split by paragraphs first
    paragraphs = re.split(r'\n\s*\n', text)

    chunks = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) > chunk_size and current:
            chunks.append(current.strip())
            current = ""
            if len(chunks) >= max_chunks:
                break
        current += para + "\n\n"

    if current.strip() and len(chunks) < max_chunks:
        chunks.append(current.strip())

    return chunks[:max_chunks]


class BookAnalyzer:
    """Analyzes a book's writing style and patterns using LLM."""

    def __init__(self, role_name: str = "prophet", model_override: Optional[Dict[str, Any]] = None):
        self.role_name = role_name
        self.model_override = model_override

    def analyze_chunk(self, chunk: str) -> Dict[str, Any]:
        prompt = ANALYSIS_PROMPT.format(chunk=chunk)
        raw = call_llm(prompt, role_name=self.role_name, temperature=0.3,
                       model_override=self.model_override)
        result = parse_json_response(raw)
        if result.get("_parse_error"):
            return {"_error": "Failed to parse analysis", "_raw": result.get("_raw", "")}
        return result

    def synthesize(self, analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
        import json
        analyses_text = json.dumps(analyses, ensure_ascii=False, indent=2)
        if len(analyses_text) > 15000:
            analyses_text = analyses_text[:15000] + "\n... (truncated)"

        prompt = SYNTHESIS_PROMPT.format(analyses=analyses_text)
        raw = call_llm(prompt, role_name=self.role_name, temperature=0.3,
                       model_override=self.model_override)
        result = parse_json_response(raw)
        if result.get("_parse_error"):
            return {"_error": "Failed to parse synthesis", "_raw": result.get("_raw", "")}
        return result

    def analyze_book(
        self,
        text: str,
        chunk_size: int = CHUNK_SIZE,
        max_chunks: int = MAX_CHUNKS,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """Full book analysis pipeline.

        Args:
            text: Full book text.
            chunk_size: Characters per chunk.
            max_chunks: Maximum number of chunks.
            progress_callback: Optional callback(current, total, message).

        Returns:
            Master analysis dict.
        """
        chunks = split_book(text, chunk_size, max_chunks)
        if not chunks:
            return {"error": "Book text is empty"}

        total = len(chunks)
        analyses = [None] * total

        # Parallel chunk analysis with bounded concurrency
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self.analyze_chunk, chunk): i
                for i, chunk in enumerate(chunks)
            }
            done = 0
            for future in as_completed(futures):
                i = futures[future]
                analyses[i] = future.result()
                done += 1
                if progress_callback:
                    progress_callback(done, total + 1, f"分析第 {done}/{total} 段...")

        if progress_callback:
            progress_callback(total, total + 1, "综合分析结果...")

        synthesis = self.synthesize(analyses)
        synthesis["_chunk_count"] = total
        synthesis["_raw_analyses"] = analyses

        if progress_callback:
            progress_callback(total + 1, total + 1, "分析完成")

        return synthesis
