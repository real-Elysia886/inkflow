"""CLI entry point for inkflow skill lifecycle management.

Commands:
    create   - Create a new skill
    update   - Update an existing skill
    list     - List all skills
    rollback - Rollback to a previous version
    versions - List versions of a skill
    cleanup  - Clean up old versions
    discover - Discover and list all loadable skills via registry
    install  - Install a skill to Claude Code

Usage:
    python -m inkflow.skill_engine.skill_cli create --type prophet --slug my-prophet --name "My Prophet"
    python -m inkflow.skill_engine.skill_cli list
    python -m inkflow.skill_engine.skill_cli discover
"""

import argparse
import json
import sys
from pathlib import Path

from inkflow.skill_engine.skill_presets import (
    get_skill_preset,
    list_skill_types,
    resolve_storage_root,
)
from inkflow.skill_engine.skill_writer import (
    create_skill,
    update_skill,
    list_skills,
    slugify,
)
from inkflow.skill_engine.version_manager import (
    list_versions,
    rollback,
    cleanup_old_versions,
    backup_current_version,
)
from inkflow.skill_engine.registry import SkillRegistry


def cmd_create(args):
    """Create a new skill."""
    base_dir = resolve_storage_root(base_dir=args.base_dir)
    slug = slugify(args.slug or args.name or "unnamed")

    preset = get_skill_preset(args.type)
    meta = {
        "skill_type": args.type,
        "display_name": args.name or preset["display_name"],
        "description": args.description or preset["description"],
        "provider": args.provider or preset["default_provider"],
        "model": args.model or preset["default_model"],
        "temperature": args.temperature if args.temperature is not None else preset["default_temperature"],
        "max_tokens": args.max_tokens or preset["default_max_tokens"],
    }

    # Load prompt content if provided
    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        if prompt_path.exists():
            meta["prompt_content"] = prompt_path.read_text(encoding="utf-8")

    # Load samples if provided
    if args.samples_file:
        samples_path = Path(args.samples_file)
        if samples_path.exists():
            meta["samples_content"] = json.loads(samples_path.read_text(encoding="utf-8"))

    # Load custom agent.py if provided
    agent_code = None
    if args.agent_file:
        agent_path = Path(args.agent_file)
        if agent_path.exists():
            agent_code = agent_path.read_text(encoding="utf-8")

    skill_dir = create_skill(base_dir, slug, meta, agent_code)
    print(f"Skill created at: {skill_dir}")


def cmd_update(args):
    """Update an existing skill."""
    base_dir = resolve_storage_root(base_dir=args.base_dir)
    skill_dir = base_dir / args.type / args.slug

    if not skill_dir.exists():
        print(f"Error: skill directory not found: {skill_dir}", file=sys.stderr)
        sys.exit(1)

    agent_patch = None
    prompt_patch = None
    config_patch = None

    if args.agent_file:
        agent_path = Path(args.agent_file)
        if agent_path.exists():
            agent_patch = agent_path.read_text(encoding="utf-8")

    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        if prompt_path.exists():
            prompt_patch = prompt_path.read_text(encoding="utf-8")

    if args.config_json:
        config_patch = json.loads(args.config_json)

    new_version = update_skill(skill_dir, agent_patch, prompt_patch, config_patch)
    print(f"Updated to version: {new_version}")


def cmd_list(args):
    """List all skills."""
    base_dir = resolve_storage_root(base_dir=args.base_dir)
    skills = list_skills(base_dir)

    if not skills:
        print("No skills found.")
        return

    # Filter by type if specified
    if args.type:
        skills = [s for s in skills if s["skill_type"] == args.type]

    print(f"{'Type':<12} {'Slug':<15} {'Display Name':<20} {'Version':<8} {'Updated':<20}")
    print("-" * 75)
    for s in skills:
        print(
            f"{s['skill_type']:<12} {s['slug']:<15} {s['display_name']:<20} "
            f"{s['version']:<8} {s['updated_at'][:16]:<20}"
        )


def cmd_versions(args):
    """List versions of a skill."""
    base_dir = resolve_storage_root(base_dir=args.base_dir)
    skill_dir = base_dir / args.type / args.slug

    if not skill_dir.exists():
        print(f"Error: skill directory not found: {skill_dir}", file=sys.stderr)
        sys.exit(1)

    versions = list_versions(skill_dir)
    if not versions:
        print(f"No archived versions for {args.type}/{args.slug}")
        return

    print(f"{'Version':<15} {'Archived At':<20} {'Files'}")
    print("-" * 50)
    for v in versions:
        print(f"{v['version']:<15} {v['archived_at']:<20} {', '.join(v['files'])}")


def cmd_rollback(args):
    """Rollback a skill to a previous version."""
    base_dir = resolve_storage_root(base_dir=args.base_dir)
    skill_dir = base_dir / args.type / args.slug

    if not skill_dir.exists():
        print(f"Error: skill directory not found: {skill_dir}", file=sys.stderr)
        sys.exit(1)

    success = rollback(skill_dir, args.version)
    if not success:
        sys.exit(1)


def cmd_cleanup(args):
    """Clean up old versions."""
    base_dir = resolve_storage_root(base_dir=args.base_dir)
    skill_dir = base_dir / args.type / args.slug

    if not skill_dir.exists():
        print(f"Error: skill directory not found: {skill_dir}", file=sys.stderr)
        sys.exit(1)

    cleanup_old_versions(skill_dir)


def cmd_discover(args):
    """Discover and list all loadable skills via registry."""
    registry = SkillRegistry(base_dir=args.base_dir)
    count = registry.discover()

    if count == 0:
        print("No skills discovered.")
        return

    print(f"Discovered {count} skill(s):\n")
    for info in registry.list():
        print(f"  [{info.skill_type}] {info.slug}")
        print(f"    Name: {info.display_name}")
        print(f"    Class: {info.agent_class.__name__}")
        print(f"    Path: {info.skill_dir}")
        print()


def cmd_install(args):
    """Install a skill to Claude Code skills directory."""
    import shutil
    import re

    base_dir = resolve_storage_root(base_dir=args.base_dir)
    skill_dir = base_dir / args.type / args.slug

    if not skill_dir.exists():
        print(f"Error: skill directory not found: {skill_dir}", file=sys.stderr)
        sys.exit(1)

    meta_file = skill_dir / "meta.json"
    if not meta_file.exists():
        print(f"Error: meta.json not found in {skill_dir}", file=sys.stderr)
        sys.exit(1)

    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)

    command_name = meta.get("artifacts", {}).get("command_name", f"{args.type}-{args.slug}")

    # Determine Claude Code skills directory
    claude_skills_dir = Path.home() / ".claude" / "skills" / command_name

    if claude_skills_dir.exists() and not args.force:
        print(f"Error: {claude_skills_dir} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    if claude_skills_dir.exists() and args.force:
        shutil.rmtree(claude_skills_dir)

    claude_skills_dir.mkdir(parents=True, exist_ok=True)

    # Write SKILL.md for Claude Code
    skill_md = f"""---
name: inkflow-{command_name}
description: "{meta.get('description', '')}"
user-invocable: true
---

# {meta.get('display_name', args.slug)} - InkFlow Skill

**Type:** {args.type}
**Slug:** {args.slug}
**Version:** {meta.get('lifecycle', {}).get('version', 'v1')}

## Description

{meta.get('description', '')}

## Usage

This is an inkflow skill agent. To use it:

```python
from inkflow.skill_engine.registry import SkillRegistry

registry = SkillRegistry()
registry.discover()
agent = registry.instantiate("{args.type}", "{args.slug}")
result = agent.execute(world_state)
```

## Agent Class

Import from: `skills.{args.type}.{args.slug}.agent`

## Configuration

- Provider: {meta.get('engine', {}).get('provider', 'N/A')}
- Model: {meta.get('engine', {}).get('model', 'N/A')}
- Temperature: {meta.get('engine', {}).get('temperature', 'N/A')}
"""

    (claude_skills_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    # Write install metadata
    install_meta = {
        "host": "claude-code",
        "command_name": command_name,
        "skill_type": args.type,
        "slug": args.slug,
        "version": meta.get("lifecycle", {}).get("version", "v1"),
        "source_skill_dir": str(skill_dir),
        "installed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }
    (claude_skills_dir / ".inkflow-install.json").write_text(
        json.dumps(install_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Installed to: {claude_skills_dir}")
    print(f"Command name: /inkflow-{command_name}")


def main():
    parser = argparse.ArgumentParser(
        description="inkflow Skill Engine CLI",
        prog="inkflow-skill",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Common arguments
    type_arg = lambda p: p.add_argument("--type", "-t", required=True, help="Skill type (prophet, writer, etc.)")
    slug_arg = lambda p: p.add_argument("--slug", "-s", required=True, help="Skill slug (unique identifier)")
    base_dir_arg = lambda p: p.add_argument("--base-dir", "-d", help="Override skills base directory")

    # create
    p_create = subparsers.add_parser("create", help="Create a new skill")
    type_arg(p_create)
    p_create.add_argument("--slug", "-s", help="Skill slug (auto-generated from name if omitted)")
    p_create.add_argument("--name", "-n", help="Display name")
    p_create.add_argument("--description", help="Skill description")
    p_create.add_argument("--provider", help="LLM provider")
    p_create.add_argument("--model", help="Model name")
    p_create.add_argument("--temperature", type=float, help="Temperature")
    p_create.add_argument("--max-tokens", type=int, help="Max tokens")
    p_create.add_argument("--prompt-file", help="Path to prompt.md content")
    p_create.add_argument("--samples-file", help="Path to samples.json content")
    p_create.add_argument("--agent-file", help="Path to custom agent.py")
    base_dir_arg(p_create)

    # update
    p_update = subparsers.add_parser("update", help="Update an existing skill")
    type_arg(p_update)
    slug_arg(p_update)
    p_update.add_argument("--agent-file", help="Path to new agent.py")
    p_update.add_argument("--prompt-file", help="Path to prompt patch")
    p_update.add_argument("--config-json", help="JSON string of config overrides")
    base_dir_arg(p_update)

    # list
    p_list = subparsers.add_parser("list", help="List all skills")
    p_list.add_argument("--type", "-t", help="Filter by skill type")
    base_dir_arg(p_list)

    # versions
    p_versions = subparsers.add_parser("versions", help="List versions of a skill")
    type_arg(p_versions)
    slug_arg(p_versions)
    base_dir_arg(p_versions)

    # rollback
    p_rollback = subparsers.add_parser("rollback", help="Rollback to a previous version")
    type_arg(p_rollback)
    slug_arg(p_rollback)
    p_rollback.add_argument("--version", "-v", required=True, help="Version to rollback to")
    base_dir_arg(p_rollback)

    # cleanup
    p_cleanup = subparsers.add_parser("cleanup", help="Clean up old versions")
    type_arg(p_cleanup)
    slug_arg(p_cleanup)
    base_dir_arg(p_cleanup)

    # discover
    p_discover = subparsers.add_parser("discover", help="Discover all loadable skills")
    base_dir_arg(p_discover)

    # install
    p_install = subparsers.add_parser("install", help="Install skill to Claude Code")
    type_arg(p_install)
    slug_arg(p_install)
    p_install.add_argument("--force", "-f", action="store_true", help="Force overwrite if exists")
    base_dir_arg(p_install)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "create": cmd_create,
        "update": cmd_update,
        "list": cmd_list,
        "versions": cmd_versions,
        "rollback": cmd_rollback,
        "cleanup": cmd_cleanup,
        "discover": cmd_discover,
        "install": cmd_install,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
