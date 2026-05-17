import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

from inkflow.memory.world_state import WorldState
from skills.prophet.agent import ProphetAgent
from skills.writer.agent import WriterAgent
from skills.librarian.agent import LibrarianAgent

# 初始化世界状态（假设第2章已写完）
world = WorldState()
world.world_setting = """
修仙世界，境界分为：炼气、筑基、金丹、元婴、化神。
主角林风，雷灵根，出身平凡山村，被青云宗破格收录。
掌门青云子（元婴期）对林风暗藏期待，外门女弟子苏雨是林风的好友。
"""
world.add_character("林风", "主角，雷灵根，筑基初期", "坚韧、重情义")
world.add_character("掌门青云子", "青云宗掌门，元婴期", "神秘莫测，暗中观察")
world.add_character("苏雨", "外门弟子，水灵根", "温柔、善良")
world.add_chapter_summary(1, "林风灵根觉醒，被青云宗收为弟子。")
world.add_chapter_summary(2, "宗门小比上，林风越级击败筑基师兄，引起掌门注意。")
world.add_foreshadowing("掌门青云子为何对林风特别上心？", 1)

# 创建 Agent
prophet = ProphetAgent("skills/prophet")
writer = WriterAgent("skills/writer")
librarian = LibrarianAgent("skills/librarian")

print("=" * 60)
print("InkFlow 流水线启动：正在创作第3章...")
print("=" * 60)

# 1. Prophet 生成大纲
print("\n[Prophet] 生成大纲...")
outline = prophet.execute(world, chapter_number=3)
print(f"大纲标题: {outline.get('chapter_title')}")
print(f"概要: {outline.get('chapter_summary')}")

# 2. Writer 撰写正文
print("\n[Writer] 写作中...")
chapter_content = writer.execute(world, outline)
print(f"生成字数: {len(chapter_content)}")

# 3. 展示部分正文
print("\n--- 正文预览（前200字） ---")
print(chapter_content[:200] + "...")

# 4. Librarian 归档
print("\n[Librarian] 归档处理...")
archive_result = librarian.execute(
    world_state=world,
    chapter_content=chapter_content,
    chapter_number=3
)
print(f"摘要: {archive_result.get('chapter_summary')}")
print(f"新伏笔: {archive_result.get('new_foreshadowings')}")
print(f"角色更新: {archive_result.get('character_updates')}")

# 5. 验证 WorldState
print(f"\n世界状态已更新: 当前 {world.current_chapter} 章, "
      f"摘要 {len(world.chapter_summaries)} 条, "
      f"伏笔 {len(world.foreshadowing_pool)} 个 (resolved: {sum(1 for f in world.foreshadowing_pool if f.status == 'resolved')})")