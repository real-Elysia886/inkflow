"""Shared LLM utilities — single source of truth for the whole package."""

import copy
import json
import os
import time
import threading
from typing import Dict, Any, Optional
from datetime import datetime

from openai import OpenAI

from inkflow.core.llm_client import LLMClientManager


class TokenStats:
    """Thread-safe token usage accumulator."""
    def __init__(self):
        self._lock = threading.Lock()
        self._total_prompt = 0
        self._total_completion = 0
        self._calls: list = []  # recent calls for breakdown
        self._max_history = 100

    def accumulate(self, prompt_tokens: int, completion_tokens: int, role: str = "", model: str = ""):
        with self._lock:
            self._total_prompt += prompt_tokens
            self._total_completion += completion_tokens
            self._calls.append({
                "time": datetime.now().isoformat(),
                "role": role,
                "model": model,
                "prompt": prompt_tokens,
                "completion": completion_tokens,
            })
            if len(self._calls) > self._max_history:
                self._calls = self._calls[-self._max_history:]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_prompt": self._total_prompt,
                "total_completion": self._total_completion,
                "total": self._total_prompt + self._total_completion,
                "call_count": len(self._calls),
                "recent_calls": list(self._calls[-20:]),
            }

    def reset(self):
        with self._lock:
            self._total_prompt = 0
            self._total_completion = 0
            self._calls.clear()


_token_stats = TokenStats()


def parse_json_response(raw: str) -> Dict[str, Any]:
    """Parse JSON from LLM response with robust fallback."""
    raw = raw.strip()

    # 1. Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2. raw_decode: find the first valid JSON object (handles any nesting depth)
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 3. Fallback: first '{' to last '}'
    start, end = raw.find('{'), raw.rfind('}')
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

    return {"_parse_error": True, "_raw": raw[:500]}


def _build_override_client(override: Dict[str, Any]) -> tuple[OpenAI, str]:
    """Build an OpenAI client from a model override dict.

    override keys: provider, base_url, api_key_env, api_key, model_name
    Returns (client, model_name).
    """
    base_url = override.get("base_url", "")
    api_key = override.get("api_key", "")
    api_key_env = override.get("api_key_env", "")

    if not api_key and api_key_env:
        api_key = os.getenv(api_key_env, "")

    # If provider name given, try to resolve from config
    if not base_url and override.get("provider"):
        manager = LLMClientManager.get_instance()
        provider_cfg = manager.providers.get(override["provider"], {})
        base_url = provider_cfg.get("base_url", "")
        if not api_key:
            env = provider_cfg.get("api_key_env", "")
            api_key = os.getenv(env, "")

    if not base_url:
        raise ValueError("model_override requires 'base_url' or 'provider'")

    client = OpenAI(api_key=api_key or "none", base_url=base_url)
    model_name = override.get("model_name", "")
    return client, model_name


def call_llm(
    prompt: Optional[str] = None,
    role_name: str = "prophet",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    json_mode: bool = True,
    max_retries: int = 3,
    model_override: Optional[Dict[str, Any]] = None,
    messages: Optional[list] = None,
    on_chunk: Optional[callable] = None,
) -> str:
    """LLM call with exponential backoff retry (2s→4s→8s).

    Args:
        prompt: User prompt string (ignored if messages is provided).
        messages: Optional list of message dicts (role/content).
        model_override: Optional dict to override the role's default model config.
            Keys: provider, base_url, api_key_env, api_key, model_name, temperature, max_tokens
        on_chunk: Optional callback for streaming. Called with each text chunk as it arrives.
            Only used when json_mode=False.
    """
    manager = LLMClientManager.get_instance()

    if model_override:
        client, override_model = _build_override_client(model_override)
        model = override_model or manager.get_role_params(role_name)["model"]
        if temperature is None:
            temperature = model_override.get("temperature", 0.7)
        if max_tokens is None:
            max_tokens = model_override.get("max_tokens", 4096)
    else:
        client = manager.get_client(role_name)
        model_params = manager.get_role_params(role_name)
        model = model_params["model"]
        if temperature is None:
            temperature = model_params["temperature"]
        if max_tokens is None:
            max_tokens = model_params["max_tokens"]

    if messages is None:
        if prompt is None:
            raise ValueError("Either 'prompt' or 'messages' must be provided.")
        messages = [{"role": "user", "content": prompt}]
    else:
        messages = copy.deepcopy(messages)

    if json_mode:
        # Ensure prompt contains "json" for API compatibility
        all_text = " ".join(m.get("content", "") for m in messages).lower()
        if "json" not in all_text:
            messages[-1]["content"] += "\n\n请以 JSON 格式输出。"

    kwargs = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
        "timeout": 120,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    use_stream = on_chunk is not None and not json_mode
    if use_stream:
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}

    last_error = None
    for attempt in range(max_retries):
        try:
            if use_stream:
                full_text = ""
                for chunk in client.chat.completions.create(**kwargs):
                    if chunk.choices and chunk.choices[0].delta.content:
                        delta = chunk.choices[0].delta.content
                        full_text += delta
                        on_chunk(delta)
                    if chunk.usage:
                        _token_stats.accumulate(chunk.usage.prompt_tokens, chunk.usage.completion_tokens, role_name, model)
                return full_text
            else:
                response = client.chat.completions.create(**kwargs)
                if response.usage:
                    _token_stats.accumulate(response.usage.prompt_tokens, response.usage.completion_tokens, role_name, model)
                return response.choices[0].message.content
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            is_transient = any(kw in error_str for kw in (
                "rate_limit", "429", "500", "502", "503",
                "timeout", "connection", "connect", "reset", "abort",
            ))
            if is_transient and attempt < max_retries - 1:
                wait = min(2 ** (attempt + 1), 32)
                print(f"[LLM] Retry {attempt+1}/{max_retries} after {wait}s: {type(e).__name__}")
                time.sleep(wait)
                continue
            raise

    raise Exception(f"LLM call failed after {max_retries} retries: {last_error}")
