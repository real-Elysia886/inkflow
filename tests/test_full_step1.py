import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

from inkflow.memory.world_state import WorldState
from skills.prophet.agent import ProphetAgent

# 1. 初始化或加载故事世界
world = WorldState()
world.world_setting = "修仙世界，境界分为：炼气、筑基、金丹、元婴、化神。主角林风拥有雷灵根，性格坚韧。"
world.add_character("林风", "主角，雷灵根，来自山村", "坚韧、重情义")
world.add_character("掌门青云子", "宗门掌门，元婴期", "深不可测，对林风有期待")
world.current_chapter = 2  # 表示已经写了2章

# 手动填充前两章摘要（未来是 Librarian 自动生成）
world.chapter_summaries = [
    "第一章：灵根觉醒，林风被检测出雷灵根，破格进入宗门。",
    "第二章：宗门小比，林风越级战胜筑基师兄，声名鹊起。"
]

# 2. 创建一个 Prophet
prophet = ProphetAgent(skill_path="skills/prophet")

# 3. 生成第三章大纲（自动使用 memory）
outline = prophet.execute(world, chapter_number=3)

print("📋 第三章大纲")
print("章节标题:", outline.get("chapter_title"))
print("章节概要:", outline.get("chapter_summary"))
print("新角色:", outline.get("new_characters"))
print("关键事件:", outline.get("key_events"))
print("伏笔:", outline.get("foreshadowing"))