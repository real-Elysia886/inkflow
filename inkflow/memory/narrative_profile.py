"""NarrativeStrategyProfile — Distilled narrative structure from a reference book.

This profile captures the structural "fingerprint" of a book's storytelling:
how chapters are paced, how multiple plotlines are woven, how foreshadowing
is managed, and how tension builds. It's injected into the OutlineWriter's
prompt to make it generate outlines that mimic the reference book's structure.
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, ConfigDict


class NarrativeStrategyProfile(BaseModel):
    """Narrative structure profile distilled from a reference book."""
    model_config = ConfigDict(populate_by_name=True)

    source_book: str = ""
    chapter_function_pattern: str = ""  # 章节功能分布规律
    pov_pattern: str = ""               # POV切换频率与规律
    foreshadowing_density: str = ""     # 伏笔密度与平均回收周期
    multiline_style: str = ""           # 多线叙事编排方式
    info_release: str = ""              # 信息释放梯度
    tension_template: str = ""          # 张力弧线宏观走势
    conflict_escalation: str = ""       # 冲突升级阶梯
    emotional_rhythm: str = ""          # 情绪节奏模板
    chapter_structure: str = ""         # 单章内部结构模板

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "NarrativeStrategyProfile":
        return cls.model_validate(data)

    @classmethod
    def from_analysis(cls, analysis: dict, source_book: str = "") -> "NarrativeStrategyProfile":
        """Create profile from BookAnalyzer synthesis output."""
        ns = analysis.get("narrative_structure", {})
        return cls(
            source_book=source_book or analysis.get("book_title", "未知作品"),
            chapter_function_pattern=ns.get("chapter_function_pattern", ""),
            pov_pattern=ns.get("pov_pattern", ""),
            foreshadowing_density=ns.get("foreshadowing_density", ""),
            multiline_style=ns.get("multiline_style", ""),
            info_release=ns.get("info_release", ""),
            tension_template=ns.get("tension_template", ""),
            conflict_escalation=ns.get("conflict_escalation", ""),
            emotional_rhythm=ns.get("emotional_rhythm", ""),
            chapter_structure=ns.get("chapter_structure", ""),
        )

    def is_empty(self) -> bool:
        """Check if profile has any meaningful content."""
        return not any([
            self.chapter_function_pattern, self.pov_pattern,
            self.foreshadowing_density, self.multiline_style,
            self.info_release, self.tension_template,
            self.conflict_escalation, self.emotional_rhythm,
        ])

    def to_prompt_section(self) -> str:
        """Format profile as a prompt section for injection into OutlineWriter/governance."""
        if self.is_empty():
            return ""

        lines = [f"## 叙事结构策略（来自《{self.source_book}》）"]
        fields = [
            ("章节功能节奏", self.chapter_function_pattern),
            ("POV 切换规律", self.pov_pattern),
            ("伏笔密度与回收周期", self.foreshadowing_density),
            ("多线编排方式", self.multiline_style),
            ("信息释放梯度", self.info_release),
            ("张力弧线模板", self.tension_template),
            ("冲突升级模式", self.conflict_escalation),
            ("情绪节奏", self.emotional_rhythm),
            ("单章结构模板", self.chapter_structure),
        ]
        for label, value in fields:
            if value:
                lines.append(f"- {label}: {value}")
        lines.append("")
        lines.append("**重要：大纲的结构安排必须严格符合上述叙事结构策略。**")
        return "\n".join(lines)
