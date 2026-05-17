"""Core skill CRUD operations for inkflow.

Creates, updates, and lists skill directories, writing Python, YAML, and JSON
artifacts. This is the main engine for the inkflow skill lifecycle.
"""

import json
import re
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

from inkflow.skill_engine.skill_presets import (
    get_skill_preset,
    normalize_skill_type,
    COMMON_KNOWLEDGE_DIRS,
)
from inkflow.skill_engine.skill_schema import (
    enrich_skill_meta,
    sync_legacy_fields,
    build_manifest,
)
from inkflow.skill_engine.version_manager import backup_artifacts

SECTION_HEADING_RE = re.compile(r"^##\s+.+$", re.MULTILINE)

# ──────────────────────────────────────────────
# Agent.py template
# ──────────────────────────────────────────────

AGENT_PY_TEMPLATE = '''\
# inkflow/skills/{skill_type}/{slug}/agent.py
"""{display_name} Agent.

{description}
"""

from pathlib import Path
from typing import Dict, Any
from inkflow.core.base_skill import BaseSkill
from inkflow.memory.world_state import WorldState
from inkflow.utils.llm_utils import call_llm, parse_json_response


class {class_name}(BaseSkill):
    """{display_name} skill agent."""

    def __init__(self, skill_path: str = None):
        if skill_path is None:
            skill_path = str(Path(__file__).parent)
        super().__init__(skill_path, role_name="{role_name}")

    def execute(self, world_state: WorldState, **kwargs) -> Dict[str, Any]:
        context = self._build_context(world_state, **kwargs)

        messages = [
            {{"role": "system", "content": self.system_prompt}},
        ]

        if self.few_shots:
            for shot in self.few_shots:
                messages.append({{"role": "user", "content": shot.get("input_context", "")}})
                messages.append({{"role": "assistant", "content": str(shot.get("output", ""))}})

        messages.append({{"role": "user", "content": context}})

        raw = call_llm(
            messages=messages,
            role_name=self.role_name,
            temperature=self.model_params["temperature"],
            max_tokens=self.model_params["max_tokens"],
            json_mode=True,
        )
        return parse_json_response(raw)

    def _build_context(self, world: WorldState, **kwargs) -> str:
        recent = world.get_recent_summaries(n=5)
        idx_start = world.current_chapter - len(recent) + 1 if recent else 1
        recent_text = "\\n".join(
            f"第{{idx_start + i}}章: {{s}}" for i, s in enumerate(recent)
        ) if recent else "（新故事，无前文）"

        char_descriptions = "\\n".join(
            f"{{name}}: {{info.description}} ({{getattr(info, 'traits', '')}})"
            for name, info in world.characters.items()
        )

        return f"""当前世界观：
{{world.world_setting or '（未设定）'}}

已有角色：
{{char_descriptions or '（无角色）'}}

最近章节摘要：
{{recent_text}}

请根据角色执行任务，输出结构化 JSON。
"""
'''


def slugify(name: str) -> str:
    """Convert a human-readable name to a stable slug."""
    slug = name.strip().lower()
    # Keep alphanumeric, hyphens, underscores
    slug = re.sub(r"[^\w\-]", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    slug = slug.replace("_", "-")
    return slug or "unnamed"


def write_artifacts(skill_dir: Path, meta: Dict[str, Any], agent_code: str) -> None:
    """Write all skill artifacts to disk."""
    skill_dir.mkdir(parents=True, exist_ok=True)

    # agent.py
    (skill_dir / "agent.py").write_text(agent_code, encoding="utf-8")

    # prompt.md
    prompt_content = meta.get("prompt_content", "")
    if not prompt_content:
        # Generate default prompt from preset
        from inkflow.skill_engine.skill_presets import get_skill_preset
        preset = get_skill_preset(meta.get("skill_type"))
        prompt_content = preset.get("prompt_template", "You are a helpful assistant.")
    (skill_dir / "prompt.md").write_text(prompt_content, encoding="utf-8")

    # samples.json
    samples = meta.get("samples_content", [])
    (skill_dir / "samples.json").write_text(
        json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # config.yaml
    config = {
        "name": meta.get("display_name", ""),
        "description": meta.get("description", ""),
        "model_route": meta.get("engine", {}).get("model", ""),
        "temperature": meta.get("engine", {}).get("temperature", 0.7),
        "system_prompt": "prompt.md",
        "few_shots": "samples.json",
        "output_schema": meta.get("output_schema", {}),
    }
    (skill_dir / "config.yaml").write_text(
        yaml.dump(config, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )

    # manifest.json
    manifest = build_manifest(meta)
    (skill_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # meta.json
    meta = sync_legacy_fields(meta)
    (skill_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def create_skill(
    base_dir: Path,
    slug: str,
    meta: Dict[str, Any],
    agent_code: Optional[str] = None,
) -> Path:
    """Create a new skill directory with all artifacts.

    Args:
        base_dir: Root directory for skills (e.g., project_root/skills).
        slug: Unique identifier for this skill instance.
        meta: Metadata dict (will be enriched to current schema).
        agent_code: Custom agent.py content. If None, generates from template.

    Returns:
        Path to the created skill directory.
    """
    skill_type = normalize_skill_type(meta.get("skill_type"))
    preset = get_skill_preset(skill_type)
    meta = enrich_skill_meta(meta, slug, skill_type)

    skill_dir = base_dir / skill_type / slug
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Create versions directory
    (skill_dir / "versions").mkdir(exist_ok=True)

    # Create knowledge subdirectories
    for kd in COMMON_KNOWLEDGE_DIRS:
        (skill_dir / "knowledge" / kd).mkdir(parents=True, exist_ok=True)

    # Initialize lifecycle
    meta.setdefault("lifecycle", {})
    meta["lifecycle"]["created_at"] = datetime.now(timezone.utc).isoformat()
    meta["lifecycle"]["updated_at"] = datetime.now(timezone.utc).isoformat()
    meta["lifecycle"]["version"] = "v1"
    meta["lifecycle"]["corrections_count"] = 0

    # Generate agent.py if not provided
    if agent_code is None:
        class_name = f"{slug.title().replace('-', '').replace('_', '')}Agent"
        agent_code = AGENT_PY_TEMPLATE.format(
            skill_type=skill_type,
            slug=slug,
            display_name=meta.get("display_name", slug),
            description=meta.get("description", ""),
            class_name=class_name,
            role_name=slug,
        )

    meta = sync_legacy_fields(meta)
    write_artifacts(skill_dir, meta, agent_code)
    print(f"Created skill: {skill_dir}")
    return skill_dir


def update_skill(
    skill_dir: Path,
    agent_patch: Optional[str] = None,
    prompt_patch: Optional[str] = None,
    config_patch: Optional[Dict[str, Any]] = None,
) -> str:
    """Update an existing skill with patches.

    Args:
        skill_dir: Path to the existing skill directory.
        agent_patch: New agent.py content (full replacement).
        prompt_patch: Patch for prompt.md (section-level merge).
        config_patch: Dict of config.yaml overrides.

    Returns:
        The new version string.
    """
    meta_file = skill_dir / "meta.json"
    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)

    meta = enrich_skill_meta(meta, meta.get("slug", ""), meta.get("skill_type"))

    # Increment version
    current_version = meta.get("lifecycle", {}).get("version", "v1")
    version_num = current_version.replace("v", "").split("_")[0]
    try:
        new_num = int(version_num) + 1
    except ValueError:
        new_num = 1
    new_version = f"v{new_num}"

    # Backup current artifacts
    backup_dir = skill_dir / "versions" / current_version
    backup_artifacts(skill_dir, backup_dir)

    # Read current files into variables (avoid re-reading after write)
    agent_file = skill_dir / "agent.py"
    agent_code = agent_file.read_text(encoding="utf-8") if agent_file.exists() else ""

    prompt_file = skill_dir / "prompt.md"
    prompt_content = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else ""

    samples_file = skill_dir / "samples.json"
    try:
        samples_content = json.loads(samples_file.read_text(encoding="utf-8")) if samples_file.exists() else []
    except (json.JSONDecodeError, OSError):
        samples_content = []

    # Apply patches in-memory
    if agent_patch:
        agent_code = agent_patch

    if prompt_patch:
        prompt_content = merge_markdown_patch(prompt_content, prompt_patch)

    config_patch_applied = False
    if config_patch:
        config_file = skill_dir / "config.yaml"
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        else:
            config = {}
        config.update(config_patch)
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        config_patch_applied = True

    # Set content into meta for write_artifacts
    meta["prompt_content"] = prompt_content
    meta["samples_content"] = samples_content

    # Update lifecycle
    meta.setdefault("lifecycle", {})
    meta["lifecycle"]["version"] = new_version
    meta["lifecycle"]["updated_at"] = datetime.now(timezone.utc).isoformat()

    meta = sync_legacy_fields(meta)
    write_artifacts(skill_dir, meta, agent_code)

    print(f"Updated skill to {new_version}")
    return new_version


def merge_markdown_patch(existing_content: str, patch_content: str) -> str:
    """Section-level markdown merge.

    For each ## heading in the patch:
    - If the same heading exists in existing, replace that section.
    - If not, append the patch section at the end.
    """
    patch_headings = list(SECTION_HEADING_RE.finditer(patch_content))
    if not patch_headings:
        return existing_content + "\n" + patch_content

    result = existing_content

    for i, match in enumerate(patch_headings):
        start = match.start()
        end = patch_headings[i + 1].start() if i + 1 < len(patch_headings) else len(patch_content)
        section = patch_content[start:end].rstrip()

        heading = match.group().strip()
        existing_match = re.search(
            re.escape(heading) + r".*?(?=^##\s|\Z)",
            result,
            re.MULTILINE | re.DOTALL,
        )

        if existing_match:
            result = result[: existing_match.start()] + section + "\n" + result[existing_match.end() :]
        else:
            result = result.rstrip() + "\n\n" + section + "\n"

    return result


def list_skills(base_dir: Path) -> List[Dict[str, Any]]:
    """List all skills discovered under base_dir.

    Scans for skill_type/slug directories containing meta.json.
    """
    results = []
    if not base_dir.exists():
        return results

    def _add_skill(skill_dir, skill_type):
        """Add a skill directory to results if it has agent.py."""
        meta_file = skill_dir / "meta.json"
        agent_file = skill_dir / "agent.py"

        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta = enrich_skill_meta(meta, meta.get("slug", ""), meta.get("skill_type"))
                lifecycle = meta.get("lifecycle", {})
                results.append({
                    "slug": meta.get("slug", skill_dir.name),
                    "skill_type": meta.get("skill_type", skill_type),
                    "name": meta.get("name", ""),
                    "display_name": meta.get("display_name", ""),
                    "description": meta.get("description", ""),
                    "version": lifecycle.get("version", "v1"),
                    "updated_at": lifecycle.get("updated_at", ""),
                    "corrections_count": lifecycle.get("corrections_count", 0),
                    "path": str(skill_dir),
                })
            except Exception as e:
                print(f"[SkillEngine] Skill scan skip {skill_dir}: {e}")
        elif agent_file.exists():
            config_file = skill_dir / "config.yaml"
            config = {}
            if config_file.exists():
                try:
                    with open(config_file, "r", encoding="utf-8") as f:
                        config = yaml.safe_load(f) or {}
                except Exception:
                    pass
            results.append({
                "slug": skill_dir.name,
                "skill_type": skill_type,
                "name": config.get("name", skill_dir.name),
                "display_name": config.get("name", skill_dir.name),
                "description": config.get("description", ""),
                "version": "base",
                "updated_at": "",
                "corrections_count": 0,
                "path": str(skill_dir),
            })

    for skill_type_dir in sorted(base_dir.iterdir()):
        if not skill_type_dir.is_dir():
            continue
        skill_type = skill_type_dir.name

        # Check if the type directory itself is a base skill (e.g. skills/editor/agent.py)
        _add_skill(skill_type_dir, skill_type)

        # Check subdirectories for nested skills (e.g. skills/editor/distilled-editor/agent.py)
        for skill_dir in sorted(skill_type_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            _add_skill(skill_dir, skill_type)

    return results
