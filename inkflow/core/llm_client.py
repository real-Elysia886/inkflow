# inkflow/core/llm_client.py
import os
import threading
import yaml
from pathlib import Path
from openai import OpenAI
from typing import Optional, Dict, Any


class LLMClientManager:
    """集中式模型客户端管理器（线程安全）"""

    _singleton: Optional["LLMClientManager"] = None
    _singleton_lock = threading.Lock()

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "model_settings.yaml"

        with open(config_path, 'r', encoding='utf-8') as f:
            self.settings = yaml.safe_load(f) or {}

        self.providers = self.settings.get("providers", {})
        self.routing = self.settings.get("role_routing", {})
        self.default = self.settings.get("default", {})

        self._client_cache: Dict[str, OpenAI] = {}
        self._cache_lock = threading.Lock()

    def _get_provider_config(self, provider_name: str) -> Dict[str, Any]:
        provider = self.providers.get(provider_name)
        if not provider:
            raise ValueError(f"Provider '{provider_name}' not found in config.")

        api_key_env = provider.get("api_key_env")
        api_key = os.getenv(api_key_env, "") if api_key_env else ""
        if not api_key and "localhost" not in provider.get("base_url", ""):
            print(f"[WARNING] 环境变量 {api_key_env} 未设置，调用可能失败。")

        return {
            "base_url": provider.get("base_url"),
            "api_key": api_key,
        }

    def _resolve_route(self, role_name: str) -> Dict[str, Any]:
        """Resolve route for a role, falling back to base role for distilled-* names."""
        route = self.routing.get(role_name)
        if route is None and role_name.startswith("distilled-"):
            base_role = role_name[len("distilled-"):]
            route = self.routing.get(base_role)
        return route or self.default

    def get_client(self, role_name: str) -> OpenAI:
        with self._cache_lock:
            if role_name in self._client_cache:
                return self._client_cache[role_name]

            route = self._resolve_route(role_name)
            provider_name = route.get("provider")
            provider_cfg = self._get_provider_config(provider_name)

            client = OpenAI(
                api_key=provider_cfg["api_key"],
                base_url=provider_cfg["base_url"],
            )

            self._client_cache[role_name] = client
            return client

    def get_role_params(self, role_name: str) -> Dict[str, Any]:
        route = self._resolve_route(role_name)
        return {
            "model": route.get("model_name"),
            "temperature": route.get("temperature", 0.7),
            "max_tokens": route.get("max_tokens", 2048),
        }

    @classmethod
    def get_instance(cls) -> "LLMClientManager":
        with cls._singleton_lock:
            if cls._singleton is None:
                cls._singleton = cls()
            return cls._singleton

    @classmethod
    def invalidate(cls):
        """Invalidate the singleton cache (call after config changes)."""
        with cls._singleton_lock:
            cls._singleton = None
