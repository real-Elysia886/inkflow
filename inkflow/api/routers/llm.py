"""LLM configuration API router."""

import os
import threading
import yaml
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from inkflow.api.schemas.llm import (
    ProviderCreate, ProviderOut,
    RoleRouteCreate, RoleRouteOut,
    LLMSettingsOut,
)

router = APIRouter(prefix="/api/llm", tags=["llm"])

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "model_settings.yaml"
ENV_PATH = Path(__file__).parent.parent.parent.parent / ".env"
_config_lock = threading.Lock()

def _get_registry():
    from inkflow.skill_engine.registry import SkillRegistry
    return SkillRegistry.get_default()


def _load_settings() -> dict:
    with _config_lock:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise HTTPException(500, f"Config file corrupted: {e}")


def _save_settings(settings: dict):
    with _config_lock:
        # YAML 没有现成的原子写函数，先 dump 到字符串再调原子文本写
        from inkflow.utils.atomic_io import write_text_atomic
        text = yaml.dump(settings, allow_unicode=True, default_flow_style=False, sort_keys=False)
        write_text_atomic(CONFIG_PATH, text)
    # Invalidate LLMClientManager singleton so it reloads config
    from inkflow.core.llm_client import LLMClientManager
    LLMClientManager.invalidate()


def _read_env() -> dict[str, str]:
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _write_env_var(key: str, value: str):
    with _config_lock:
        env = _read_env()
        env[key] = value
        from inkflow.utils.atomic_io import write_text_atomic
        lines = [f"{k}={v}" for k, v in env.items()]
        write_text_atomic(ENV_PATH, "\n".join(lines) + "\n")
    os.environ[key] = value


@router.get("/settings", response_model=LLMSettingsOut)
def get_settings():
    settings = _load_settings()
    env = _read_env()

    providers = []
    for name, cfg in settings.get("providers", {}).items():
        api_key_env = cfg.get("api_key_env", "")
        providers.append(ProviderOut(
            name=name,
            base_url=cfg.get("base_url", ""),
            api_key_env=api_key_env,
            has_key=bool(env.get(api_key_env)),
        ))

    role_routing = []
    for role, cfg in settings.get("role_routing", {}).items():
        role_routing.append(RoleRouteOut(
            role_name=role,
            provider=cfg.get("provider", ""),
            model_name=cfg.get("model_name", ""),
            temperature=cfg.get("temperature", 0.7),
            max_tokens=cfg.get("max_tokens", 2048),
        ))

    default_cfg = settings.get("default", {})
    default = RoleRouteOut(
        role_name="default",
        provider=default_cfg.get("provider", ""),
        model_name=default_cfg.get("model_name", ""),
        temperature=default_cfg.get("temperature", 0.7),
        max_tokens=default_cfg.get("max_tokens", 2048),
    )

    # Discover active skills and their role_names
    active_skills = []
    try:
        registry = _get_registry()
        for info in registry.list():
            # Extract role_name from the agent class's __init__ defaults
            role_name = info.slug  # fallback
            try:
                defaults = info.agent_class.__init__.__defaults__
                if defaults:
                    role_name = defaults[0]
            except Exception:
                pass
            active_skills.append({
                "skill_type": info.skill_type,
                "slug": info.slug,
                "display_name": info.display_name,
                "role_name": role_name,
            })
    except Exception:
        pass

    return LLMSettingsOut(providers=providers, role_routing=role_routing, default=default, active_skills=active_skills)


@router.post("/providers", response_model=ProviderOut)
def add_provider(body: ProviderCreate):
    settings = _load_settings()
    providers = settings.setdefault("providers", {})
    if body.name in providers:
        raise HTTPException(400, f"Provider '{body.name}' already exists")

    providers[body.name] = {
        "base_url": body.base_url,
        "api_key_env": body.api_key_env,
    }
    _save_settings(settings)

    if body.api_key:
        _write_env_var(body.api_key_env, body.api_key)

    return ProviderOut(
        name=body.name,
        base_url=body.base_url,
        api_key_env=body.api_key_env,
        has_key=bool(body.api_key),
    )


@router.put("/providers/{name}")
def update_provider(name: str, body: ProviderCreate):
    settings = _load_settings()
    providers = settings.get("providers", {})
    if name not in providers:
        raise HTTPException(404, f"Provider '{name}' not found")
    providers[name] = {
        "base_url": body.base_url,
        "api_key_env": body.api_key_env,
    }
    _save_settings(settings)
    if body.api_key:
        _write_env_var(body.api_key_env, body.api_key)
    return {"ok": True}


@router.delete("/providers/{name}")
def delete_provider(name: str):
    settings = _load_settings()
    providers = settings.get("providers", {})
    if name not in providers:
        raise HTTPException(404, f"Provider '{name}' not found")
    del providers[name]
    _save_settings(settings)
    return {"ok": True}


class ApiKeyBody(BaseModel):
    api_key: str


@router.put("/providers/{name}/key")
def update_api_key(name: str, body: ApiKeyBody):
    settings = _load_settings()
    provider = settings.get("providers", {}).get(name)
    if not provider:
        raise HTTPException(404, f"Provider '{name}' not found")
    _write_env_var(provider["api_key_env"], body.api_key)
    from inkflow.core.llm_client import LLMClientManager
    LLMClientManager.invalidate()
    return {"ok": True}


@router.post("/routes", response_model=RoleRouteOut)
def add_route(body: RoleRouteCreate):
    settings = _load_settings()
    routing = settings.setdefault("role_routing", {})
    routing[body.role_name] = {
        "provider": body.provider,
        "model_name": body.model_name,
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
    }
    _save_settings(settings)
    return RoleRouteOut(
        role_name=body.role_name,
        provider=body.provider,
        model_name=body.model_name,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
    )


@router.put("/routes/{role_name}")
def update_route(role_name: str, body: RoleRouteCreate):
    settings = _load_settings()
    routing = settings.setdefault("role_routing", {})
    if role_name not in routing:
        raise HTTPException(404, f"Route '{role_name}' not found")
    routing[role_name] = {
        "provider": body.provider,
        "model_name": body.model_name,
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
    }
    _save_settings(settings)
    return RoleRouteOut(
        role_name=role_name,
        provider=body.provider,
        model_name=body.model_name,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
    )


@router.delete("/routes/{role_name}")
def delete_route(role_name: str):
    settings = _load_settings()
    routing = settings.get("role_routing", {})
    if role_name not in routing:
        raise HTTPException(404, f"Route '{role_name}' not found")
    del routing[role_name]
    _save_settings(settings)
    return {"ok": True}


@router.put("/default")
def update_default_route(body: RoleRouteCreate):
    """Update the default fallback route."""
    settings = _load_settings()
    settings["default"] = {
        "provider": body.provider,
        "model_name": body.model_name,
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
    }
    _save_settings(settings)
    return {"ok": True}


@router.put("/test")
def test_connection(provider: str):
    settings = _load_settings()
    prov = settings.get("providers", {}).get(provider)
    if not prov:
        raise HTTPException(404, f"Provider '{provider}' not found")

    env = _read_env()
    api_key = env.get(prov.get("api_key_env", ""), "")

    import httpx
    try:
        resp = httpx.get(
            f"{prov['base_url']}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        return {"ok": resp.status_code == 200, "status": resp.status_code, "detail": resp.text[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/tokens")
def get_token_stats():
    """Get accumulated token usage statistics."""
    from inkflow.utils.llm_utils import _token_stats
    return _token_stats.get_stats()


@router.post("/tokens/reset")
def reset_token_stats():
    """Reset token usage statistics."""
    from inkflow.utils.llm_utils import _token_stats
    _token_stats.reset()
    return {"ok": True}
