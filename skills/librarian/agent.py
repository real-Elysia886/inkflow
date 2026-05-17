import json
from typing import Dict, Any
from inkflow.core.base_skill import BaseSkill
from inkflow.memory.world_state import WorldState
from inkflow.utils.llm_utils import call_llm, parse_json_response

class LibrarianAgent(BaseSkill):
    """记录员：记忆压缩与伏笔管理"""
    
    def __init__(self, skill_path: str):
        super().__init__(skill_path, role_name="librarian")
    
    def execute(
        self,
        world_state: WorldState,
        chapter_content: str = "",
        chapter_number: int = None,
        **kwargs
    ) -> Dict[str, Any]:
        if chapter_number is None:
            chapter_number = getattr(world_state, 'current_chapter', 0)
        """
        对给定章节内容进行记忆压缩和状态更新
        """
        # 1. 构建 prompt
        context = self._build_context(world_state, chapter_content)

        # 2. 构建消息列表
        messages = [{"role": "system", "content": self.system_prompt}]

        if self.few_shots:
            for shot in self.few_shots:
                sample_input = json.dumps(shot["input"], ensure_ascii=False)
                sample_output = json.dumps(shot["output"], ensure_ascii=False)
                messages.append({"role": "user", "content": sample_input})
                messages.append({"role": "assistant", "content": sample_output})

        messages.append({"role": "user", "content": context})

        # 3. 调用 LLM（带容错）
        try:
            raw = call_llm(
                messages=messages,
                role_name=self.role_name,
                temperature=self.model_params["temperature"],
                max_tokens=self.model_params["max_tokens"],
                json_mode=True
            )
            result = parse_json_response(raw)
        except Exception as e:
            print(f"[WARNING] Librarian LLM call failed: {e}")
            result = {
                "chapter_summary": f"第{chapter_number}章",
                "new_foreshadowings": [],
                "resolved_foreshadowings": [],
                "character_updates": {}
            }

        # 4. 将归档结果写入 WorldState
        self._update_world_state(world_state, result, chapter_number)

        return result
    
    def _build_context(self, world_state: WorldState, chapter_content: str) -> str:
        """构建给 LLM 的完整上下文"""
        # 只给当前已知且未回收的伏笔（标记 id 方便 LLM 引用）
        pending_foreshadowings = []
        for idx, f in enumerate(world_state.foreshadowing_pool):
            if f.status == "pending":
                pending_foreshadowings.append({
                    "id": idx,
                    "detail": f.detail,
                    "planted_chapter": f.planted_chapter or "未知"
                })
        
        characters_info = {
            name: {"description": c.description, "traits": c.traits, "status": c.status}
            for name, c in world_state.characters.items()
        }

        context = f"""
已知角色：
{json.dumps(characters_info, ensure_ascii=False, indent=2)}

当前未回收的伏笔（请按 id 回收）：
{json.dumps(pending_foreshadowings, ensure_ascii=False, indent=2) if pending_foreshadowings else "（无）"}

本章正文（前5000字）：
{chapter_content[:5000]}
"""
        return context
    
    def _update_world_state(
        self,
        world_state: WorldState,
        result: Dict[str, Any],
        chapter_number: int
    ):
        """将 LLM 输出的结构化结果应用到 WorldState，容错处理"""
        
        # 1. 添加章节摘要
        summary = result.get("chapter_summary", "")
        world_state.add_chapter_summary(chapter_number, summary)
        
        # 2. 处理新伏笔（兼容不同格式）
        new_foreshadowings = result.get("new_foreshadowings", [])
        for fs in new_foreshadowings:
            if isinstance(fs, dict):
                detail = fs.get("detail", str(fs))
            else:
                detail = str(fs)
            world_state.add_foreshadowing(
                detail=detail,
                related_chapter=chapter_number
            )
        
        # 3. 标记已回收的伏笔（兼容数字和字典）
        resolved_items = result.get("resolved_foreshadowings", [])
        for item in resolved_items:
            if isinstance(item, dict):
                rid = item.get("id")
            else:
                rid = item
            
            # 确保 rid 是整数且在有效范围内
            if isinstance(rid, int) and 0 <= rid < len(world_state.foreshadowing_pool):
                world_state.foreshadowing_pool[rid].status = "resolved"
        
        # 4. 更新角色状态（安全合并）
        char_updates = result.get("character_updates", {})
        for name, update_info in char_updates.items():
            if name in world_state.characters:
                # 追加更新记录，避免覆盖原有信息
                existing = world_state.characters[name]
                update_str = str(update_info) if not isinstance(update_info, str) else update_info
                existing.traits = f"{existing.traits} | 第{chapter_number}章更新: {update_str}"
            else:
                # 未知角色自动注册
                desc = str(update_info) if not isinstance(update_info, str) else update_info
                world_state.add_character(name, desc, f"第{chapter_number}章登场")