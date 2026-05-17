"""Metadata schema for inkflow skills.

Defines the canonical schema structure, builds artifact names, and enriches
raw metadata to the current schema version.
"""

import copy
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from inkflow.skill_engine.skill_presets import (
    get_skill_preset,
    normalize_skill_type,
    COMMON_KNOWLEDGE_DIRS,
)

SCHEMA_VERSION = "1"

# Files that form the canonical artifact set for each skill
PRIMARY_ARTIFACTS = (
    "agent.py",
    "config.yaml",
    "prompt.md",
    "samples.json",
    "manifest.json",
    "meta.json",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_artifact_names(slug: str, skill_type: str) -> Dict[str, str]:
    """Generate all artifact filenames from slug and skill type."""
    return {
        "agent_file": "agent.py",
        "config_file": "config.yaml",
        "prompt_file": "prompt.md",
        "samples_file": "samples.json",
        "manifest_file": "manifest.json",
        "meta_file": "meta.json",
        "skill_name": f"inkflow-{skill_type}-{slug}",
        "command_name": f"{skill_type}-{slug}",
    }


def build_manifest(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Build a manifest.json structure for install/discovery."""
    return {
        "manifest_version": "1",
        "id": meta.get("id", ""),
        "kind": meta.get("kind", "inkflow-skill"),
        "skill_type": meta.get("skill_type", ""),
        "slug": meta.get("slug", ""),
        "display_name": meta.get("display_name", ""),
        "description": meta.get("description", ""),
        "entrypoints": {
            "agent": "agent.py",
            "config": "config.yaml",
            "prompt": "prompt.md",
            "samples": "samples.json",
        },
        "artifacts": list(PRIMARY_ARTIFACTS),
        "capabilities": ["execute", "configure", "prompt"],
        "engine": {
            "name": "inkflow",
            "version": "0.1.0",
            "skill_type": meta.get("skill_type", ""),
            "provider": meta.get("engine", {}).get("provider", meta.get("provider", "")),
            "model": meta.get("engine", {}).get("model", meta.get("model", "")),
        },
        "install": {
            "compatible_runtimes": ["inkflow-cli", "claude-code"],
            "min_schema_version": SCHEMA_VERSION,
        },
    }


def enrich_skill_meta(
    meta: Dict[str, Any],
    slug: str,
    skill_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Upgrade raw metadata to the current schema version.

    This is the central normalization function. It takes any metadata dict
    (partial or legacy) and produces a fully-populated schema v1 dict.
    """
    meta = copy.deepcopy(meta)

    # Resolve skill type
    resolved_type = normalize_skill_type(skill_type or meta.get("skill_type"))
    preset = get_skill_preset(resolved_type)

    # Ensure sub-dicts exist
    meta.setdefault("lifecycle", {})
    meta.setdefault("engine", {})

    # Identity
    meta["schema_version"] = SCHEMA_VERSION
    meta["slug"] = slug
    meta["kind"] = "inkflow-skill"
    meta["skill_type"] = resolved_type

    display_name = meta.get("display_name") or preset.get("display_name", slug)
    meta["display_name"] = display_name
    meta["name"] = f"inkflow-{resolved_type}-{slug}"
    meta["id"] = f"inkflow.{resolved_type}.{slug}"

    meta["description"] = meta.get("description") or preset.get("description", "")

    # Build artifacts
    existing_artifacts = meta.get("artifacts", {})
    artifacts = build_artifact_names(slug, resolved_type)
    artifacts.update(existing_artifacts)
    meta["artifacts"] = artifacts

    # Engine config
    meta["engine"] = {
        "name": "inkflow",
        "kind": "inkflow-skill",
        "skill_type": resolved_type,
        "provider": meta.get("provider", preset.get("default_provider", "")),
        "model": meta.get("model", preset.get("default_model", "")),
        "temperature": meta.get("temperature", preset.get("default_temperature", 0.7)),
        "max_tokens": meta.get("max_tokens", preset.get("default_max_tokens", 2048)),
        "knowledge_dirs": COMMON_KNOWLEDGE_DIRS,
    }

    # Lifecycle
    lifecycle = meta["lifecycle"]
    lifecycle.setdefault("status", "active")
    lifecycle.setdefault("created_at", now_iso())
    lifecycle["updated_at"] = now_iso()
    lifecycle.setdefault("version", "v1")
    lifecycle.setdefault("corrections_count", 0)

    # Summary
    if "summary" not in meta:
        meta["summary"] = f"[{resolved_type}] {display_name} ({slug})"

    return meta


def sync_legacy_fields(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Bidirectional sync between schema sections and legacy top-level fields."""
    lifecycle = meta.get("lifecycle", {})

    # Ensure top-level fields exist from lifecycle
    meta.setdefault("version", lifecycle.get("version", "v1"))
    meta.setdefault("created_at", lifecycle.get("created_at", now_iso()))
    meta.setdefault("updated_at", lifecycle.get("updated_at", now_iso()))
    meta.setdefault("corrections_count", lifecycle.get("corrections_count", 0))

    # Sync back into lifecycle
    lifecycle.setdefault("version", meta.get("version", "v1"))
    lifecycle.setdefault("created_at", meta.get("created_at", now_iso()))
    lifecycle["updated_at"] = meta.get("updated_at", now_iso())
    lifecycle.setdefault("corrections_count", meta.get("corrections_count", 0))

    meta["lifecycle"] = lifecycle
    return meta
