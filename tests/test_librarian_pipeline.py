import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

from inkflow.memory.world_state import WorldState
from skills.prophet.agent import ProphetAgent
from skills.librarian.agent import LibrarianAgent

# ====== 初始化故事世界 ======
world = WorldState()
world.world_setting = """
修仙世界，境界：炼气、筑基、金丹、元婴、化神。
主角林风，雷灵根，出身山村，性格坚韧且重情义。
当前所在宗门：青云宗。掌门青云子对林风寄予厚望。
"""

world.add_character("林风", "主角，雷灵根", "坚韧、重情义、筑基初期")
world.add_character("掌门青云子", "青云宗掌门，元婴期", "深不可测，暗中关注林风")
world.add_character("苏雨", "外门女弟子，林风的好友", "温柔善良，水灵根")

world.chapter_summaries = [
    "第一章：灵根觉醒。林风被检测出雷灵根，破格进入青云宗。",
    "第二章：宗门小比。林风越级战胜筑基师兄，引起掌门注意。"
]
world.current_chapter = 2

# 已有的伏笔
world.add_foreshadowing("掌门青云子为何特别关注林风？", 1)

# ====== 创建 Agent 实例 ======
prophet = ProphetAgent(skill_path="skills/prophet")
librarian = LibrarianAgent(skill_path="skills/librarian")

print("=" * 60)
print(f"📖 正在生成第 {world.current_chapter + 1} 章...")
print("=" * 60)

# 1. Prophet 生成第三章大纲
outline = prophet.execute(world)
print(f"\n📋 大纲：{outline.get('chapter_title')}")
print(f"概要：{outline.get('chapter_summary')}")
print(f"新角色：{outline.get('new_characters')}")

# 2. 模拟 Ghostwriter 将大纲扩展为正文（这里用拼接方式模拟）
mock_content = f"""
{outline.get('chapter_summary')}

清晨，林风从修炼中醒来，感觉体内的雷灵力又精纯了几分。
突然，他感应到宗门后山传来一阵异样的灵力波动...
（此处省略 2000 字剧情）
"""

# 3. Librarian 对模拟正文进行归档
print(f"\n🗂️ Librarian 正在归档第 {world.current_chapter + 1} 章...")
archive = librarian.execute(
    world_state=world,
    chapter_content=mock_content,
    chapter_number=world.current_chapter + 1
)

print(f"\n✅ 归档完成！")
print(f"章节摘要：{archive.get('chapter_summary')}")
print(f"新伏笔：{archive.get('new_foreshadowings')}")
print(f"已回收伏笔 ID：{archive.get('resolved_foreshadowings')}")
print(f"角色更新：{archive.get('character_updates')}")

# 4. 验证 WorldState 是否被正确更新
print(f"\n🌍 更新后的世界状态：")
print(f"  当前章节数：{world.current_chapter}")
print(f"  章纲列表长度：{len(world.chapter_summaries)}")
print(f"  伏笔池大小：{len(world.foreshadowing_pool)}")
print(f"  伏笔状态：{[f['status'] for f in world.foreshadowing_pool]}")

# 5. 检查最近摘要（滑动窗口）
print(f"\n📚 最近 3 章摘要：")
for i, s in enumerate(world.get_recent_summaries(3)):
    print(f"  第 {world.current_chapter - len(world.get_recent_summaries(3)) + i + 1} 章: {s}")