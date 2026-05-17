from typing import Dict, Any, Optional, Callable
from inkflow.core.base_skill import BaseSkill
from inkflow.memory.world_state import WorldState
from inkflow.utils.llm_utils import call_llm

class WriterAgent(BaseSkill):
    """作者智能体：根据大纲和记忆库撰写章节正文"""

    def __init__(self, skill_path: str):
        super().__init__(skill_path, role_name="writer")
        # 从配置中读取风格指南文件名（可选），这里直接硬编码一个默认风格
        self.style_guide = self.config.get("style_guide", "")
        if not self.style_guide:
            # 如果没有单独的风格文件，使用配置中的描述或默认值
            self.style_guide = self.config.get(
                "style_description",
                "使用流畅平实的中文，适当穿插内心独白和环境描写，节奏紧凑。"
            )

    def execute(self, world_state: WorldState, outline: Dict[str, Any] = None,
                on_chunk: Optional[Callable] = None, **kwargs) -> str:
        """
        根据大纲和世界状态撰写一章正文
        """
        # 1. 构建写作上下文
        context = self._build_context(world_state, outline)

        # 2. 构建消息
        messages = [{"role": "system", "content": self.system_prompt}]

        # 注入 few-shot 样本
        if self.few_shots:
            for shot in self.few_shots:
                sample_input = f"大纲：{shot['input']['outline']}\n世界观：{shot['input']['world_setting']}\n角色：{shot['input']['characters']}"
                messages.append({"role": "user", "content": sample_input})
                messages.append({"role": "assistant", "content": shot['output']})

        messages.append({"role": "user", "content": context})

        # 3. 调用 LLM（使用统一工具）
        chapter_text = call_llm(
            messages=messages,
            role_name=self.role_name,
            temperature=self.model_params["temperature"],
            max_tokens=self.model_params["max_tokens"],
            json_mode=False,
            on_chunk=on_chunk
        )

        return chapter_text
    
    def _build_context(self, world_state: WorldState, outline: Dict[str, Any]) -> str:
        """构建写作所需的完整上下文（滑动窗口）"""

        # 世界观简介
        world_setting = world_state.world_setting

        # 最近章节摘要（滑动窗口，取最近5章）
        recent = world_state.get_recent_summaries(5)
        recent_text = ""
        if recent:
            idx_start = world_state.current_chapter - len(recent) + 1
            for i, summary in enumerate(recent):
                recent_text += f"第{idx_start + i}章摘要：{summary}\n"
        else:
            recent_text = "（故事开篇）"

        # 出场角色卡（只保留大纲中可能涉及的角色，这里简单列出所有角色）
        characters_text = "\n".join(
            f"- {name}: {info.description} ({info.traits})"
            for name, info in world_state.characters.items()
        )

        # 大纲内容 - 兼容 plan 和 outline 两种格式
        chapter_goal = outline.get('chapter_goal', outline.get('chapter_summary', ''))
        key_events = outline.get('key_events', [])
        if not key_events:
            # 从 must_keep 和 foreshadowing_actions 构建
            key_events = outline.get('must_keep', [])
        foreshadowing = outline.get('foreshadowing', [])
        if not foreshadowing:
            fo_actions = outline.get('foreshadowing_actions', {})
            foreshadowing = fo_actions.get('to_plant', []) + fo_actions.get('to_resolve', [])
        emotional_direction = outline.get('emotional_direction', '')
        must_keep = outline.get('must_keep', [])
        must_avoid = outline.get('must_avoid', [])
        focus_characters = outline.get('focus_characters', [])

        outline_text = f"""
章节目标：{chapter_goal}
情绪走向：{emotional_direction}
关键事件：{', '.join(key_events) if key_events else '（无）'}
需埋设的伏笔：{', '.join(foreshadowing) if foreshadowing else '（无）'}
必须保留：{', '.join(must_keep) if must_keep else '（无）'}
必须避免：{', '.join(must_avoid) if must_avoid else '（无）'}
重点角色：{', '.join(focus_characters) if focus_characters else '（无）'}
"""

        # 拼装最终 prompt
        full_prompt = f"""
{self.style_guide}

【世界观设定】
{world_setting}

【角色档案】
{characters_text}

【近期剧情回顾】
{recent_text}

【本章大纲】
{outline_text}

请开始创作本章正文。正文第一行写一个合适的章节标题，不要加"# "或"第X章"前缀，标题后空一行再开始正文。
"""
        return full_prompt