"""Skill type presets registry for inkflow.

Defines the configuration template for each skill type (strategist, prophet,
writer, editor, librarian). Each preset specifies the default LLM routing,
prompt templates, and output schema.
"""

from pathlib import Path
from typing import Dict, Any, Optional

SKILL_PRESETS: Dict[str, Dict[str, Any]] = {
    "strategist": {
        "display_name": "策略师",
        "description": "负责整体策略规划、世界观架构、情节走向设计",
        "default_provider": "openai",
        "default_model": "gpt-4o",
        "default_temperature": 0.7,
        "default_max_tokens": 4096,
        "prompt_template": "你是一位专业的小说策略师。你的任务是：\n1. 基于世界观设定，规划整体故事走向。\n2. 设计核心冲突和转折点。\n3. 确保情节逻辑自洽，节奏张弛有度。\n输出格式必须严格遵守 JSON Schema。",
        "output_schema": {
            "type": "object",
            "properties": {
                "plot_arc": {"type": "array", "items": {"type": "string"}},
                "key_conflicts": {"type": "array", "items": {"type": "string"}},
                "turning_points": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    "prophet": {
        "display_name": "大纲师",
        "description": "负责逻辑推演、章纲编写、新人物注册",
        "default_provider": "deepseek",
        "default_model": "deepseek-expert",
        "default_temperature": 0.4,
        "default_max_tokens": 4096,
        "prompt_template": "你是一位专业的小说大纲设计师。你的任务是：\n1. 基于给定的世界观设定和已有章节，为下一章制定详细大纲。\n2. 确保情节逻辑自洽，节奏张弛有度。\n3. 如需要引入新角色，必须给出完整的人物速写（姓名、身份、性格特征）。\n4. 记录任何可能成为后续伏笔的关键细节。\n输出格式必须严格遵守 JSON Schema。",
        "output_schema": {
            "type": "object",
            "properties": {
                "chapter_title": {"type": "string"},
                "chapter_summary": {"type": "string"},
                "new_characters": {"type": "array"},
                "key_events": {"type": "array"},
                "foreshadowing": {"type": "array"},
            },
        },
    },
    "writer": {
        "display_name": "写手",
        "description": "负责根据大纲撰写正文，输出完整章节文本",
        "default_provider": "ollama_local",
        "default_model": "llama3:70b",
        "default_temperature": 0.9,
        "default_max_tokens": 8192,
        "prompt_template": "你是一位专业的网络小说写手。你的任务是：\n1. 根据提供的章节大纲，撰写完整的章节正文。\n2. 保持人物性格一致，对话自然生动。\n3. 注重场景描写和氛围营造。\n4. 控制节奏，适当留白。",
        "output_schema": {
            "type": "object",
            "properties": {
                "chapter_text": {"type": "string"},
                "word_count": {"type": "integer"},
            },
        },
    },
    "editor": {
        "display_name": "编辑",
        "description": "负责审校、润色、一致性检查",
        "default_provider": "openai",
        "default_model": "gpt-4o",
        "default_temperature": 0.2,
        "default_max_tokens": 4096,
        "prompt_template": "你是一位专业的小说编辑。你的任务是：\n1. 检查章节文本的语言质量、逻辑一致性。\n2. 标记并修正错别字、语病、重复表达。\n3. 检查人物行为是否符合已设定的性格特征。\n4. 输出修改建议和修正后的文本。",
        "output_schema": {
            "type": "object",
            "properties": {
                "issues_found": {"type": "array"},
                "corrected_text": {"type": "string"},
                "editor_notes": {"type": "string"},
            },
        },
    },
    "librarian": {
        "display_name": "图书管理员",
        "description": "负责记忆管理、章节摘要生成、伏笔追踪",
        "default_provider": "deepseek",
        "default_model": "deepseek-chat",
        "default_temperature": 0.3,
        "default_max_tokens": 2048,
        "prompt_template": "你是一位图书管理员，负责管理故事的记忆库。你的任务是：\n1. 为已写完的章节生成精炼摘要。\n2. 更新角色状态和关系变化。\n3. 追踪伏笔的埋设与回收。\n4. 维护世界观的一致性。",
        "output_schema": {
            "type": "object",
            "properties": {
                "chapter_summary": {"type": "string"},
                "character_updates": {"type": "array"},
                "foreshadowing_updates": {"type": "array"},
            },
        },
    },
}

# Directories that every skill should have for knowledge storage
COMMON_KNOWLEDGE_DIRS = ["docs", "references", "samples"]


def normalize_skill_type(skill_type: Optional[str]) -> str:
    """Normalize skill type input, fallback to 'prophet'."""
    if not skill_type:
        return "prophet"
    skill_type = skill_type.strip().lower()
    if skill_type in SKILL_PRESETS:
        return skill_type
    # Fuzzy match: check if input is a substring of any preset key
    for key in SKILL_PRESETS:
        if skill_type in key or key in skill_type:
            return key
    return "prophet"


def get_skill_preset(skill_type: Optional[str]) -> Dict[str, Any]:
    """Return the full preset dict for a given skill type."""
    return SKILL_PRESETS[normalize_skill_type(skill_type)]


def list_skill_types() -> list[str]:
    """Return all available skill type names."""
    return list(SKILL_PRESETS.keys())


def resolve_storage_root(base_dir: Optional[str] = None) -> Path:
    """Resolve the base directory for skill storage."""
    if base_dir:
        return Path(base_dir).expanduser()
    # Default: project_root/skills
    project_root = Path(__file__).parent.parent.parent
    return project_root / "skills"
