# tests/test_prophet.py
import sys
from pathlib import Path
from dotenv import load_dotenv
sys.path.insert(0, str(Path(__file__).parent.parent))
from skills.prophet.agent import ProphetAgent
loaded = load_dotenv()   # 自动向上查找 .env 文件
def test_prophet_standalone():
    """测试 Prophet 能否独立生成大纲"""
    
    # 模拟记忆库
    memory_bank = {
        "world_setting": "修仙世界，境界分为：炼气、筑基、金丹、元婴、化神。主角名为林风，拥有罕见雷灵根。",
        "chapter_summaries": [
            "第一章：林风测试灵根，被发现是百年难遇的雷灵根，被宗门破格录取。",
            "第二章：宗门大比中，林风越级击败筑基师兄，引起长老注意。"
        ],
        "characters": {
            "林风": "主角，雷灵根，性格坚韧，来自小山村。",
            "掌门青云子": "元婴期大能，对林风寄予厚望。"
        }
    }
    
    agent = ProphetAgent(skill_path="skills/prophet")
    result = agent.execute(memory_bank, chapter_number=3)
    
    print("📋 大纲生成结果：")
    print(f"章节标题：{result.get('chapter_title')}")
    print(f"章节概要：{result.get('chapter_summary')}")
    print(f"新角色：{result.get('new_characters')}")
    print(f"关键事件：{result.get('key_events')}")
    print(f"伏笔：{result.get('foreshadowing')}")

if __name__ == "__main__":
    test_prophet_standalone()