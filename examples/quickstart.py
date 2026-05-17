"""
最简使用示例：Prophet → Writer → Librarian 三步生成一章

运行前：
  1. 复制 .env.example 为 .env，填入 DEEPSEEK_API_KEY
  2. uv run python examples/quickstart.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from inkflow.memory.world_state import WorldState
from skills.prophet.agent import ProphetAgent
from skills.writer.agent import WriterAgent
from skills.librarian.agent import LibrarianAgent

SKILLS = Path(__file__).resolve().parent.parent / "skills"

# 1. 初始化世界状态
world = WorldState()
world.world_setting = "架空古代，江湖门派林立，主角是一名身负血海深仇的少年剑客。"
world.add_character("陆沉", "主角，十七岁，剑术天才，性格冷峻", "复仇、孤傲、隐忍")
world.add_character("白鹿", "女主，十六岁，医术精湛，心地善良", "温柔、聪慧、倔强")

# 2. Prophet 生成大纲
prophet = ProphetAgent(str(SKILLS / "prophet"))
outline = prophet.execute(world, chapter_number=1)
print("=== 大纲 ===")
print(outline)

# 3. Writer 撰写正文
writer = WriterAgent(str(SKILLS / "writer"))
chapter_text = writer.execute(world, outline)
print("\n=== 正文（前500字）===")
print(chapter_text[:500])

# 4. Librarian 归档，更新世界状态
librarian = LibrarianAgent(str(SKILLS / "librarian"))
archive = librarian.execute(world, chapter_text, chapter_number=1)
print("\n=== 归档结果 ===")
print(archive)
print(f"\n当前章节数：{world.current_chapter}")
