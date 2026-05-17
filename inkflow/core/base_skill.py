# inkflow/core/base_skill.py
from abc import ABC, abstractmethod
from typing import Dict, Any
from pathlib import Path
import yaml
from inkflow.core.llm_client import LLMClientManager
class BaseSkill(ABC):
    """所有技能的抽象基类"""
    
    def __init__(self, skill_path: str, role_name: str):
        """
        skill_path: 该技能配置文件夹路径
        role_name: 在 model_settings.yaml 中注册的角色名，如 "prophet"
        """
        self.skill_path = Path(skill_path)
        self.role_name = role_name
        self.config = self._load_config()
        self.system_prompt = self._load_system_prompt()
        self.few_shots = self._load_few_shots()
        
        # 从集中管理器获取客户端和参数
        self.manager = LLMClientManager.get_instance()
        self.llm_client = self.manager.get_client(self.role_name)
        self.model_params = self.manager.get_role_params(self.role_name)
        
    def _load_config(self) -> Dict[str, Any]:
        """加载 config.yaml"""
        config_file = self.skill_path / "config.yaml"
        if not config_file.exists():
            raise FileNotFoundError(f"config.yaml not found in {self.skill_path}")
        with open(config_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _load_system_prompt(self) -> str:
        """加载 system prompt（从配置中指定的路径读取）"""
        prompt_path = self.skill_path / self.config.get("system_prompt", "prompt.md")
        if not prompt_path.exists():
            return self.config.get("default_prompt", "You are a helpful assistant.")
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def _load_few_shots(self) -> list:
        """加载 few-shot 样本"""
        shots_path = self.skill_path / self.config.get("few_shots", "samples.json")
        if not shots_path.exists():
            return []
        import json
        with open(shots_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @abstractmethod
    def execute(self, memory_bank, **kwargs) -> Dict[str, Any]:
        """
        执行该技能的原子操作
        memory_bank: 记忆库对象（后续会定义）
        返回：结构化的结果字典
        """
        pass
    