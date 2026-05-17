"""Tests for the inkflow skill engine lifecycle.

Tests: create → list → discover → update → rollback → cleanup
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from inkflow.core.base_skill import BaseSkill
from inkflow.skill_engine.skill_presets import (
    get_skill_preset,
    list_skill_types,
    normalize_skill_type,
)
from inkflow.skill_engine.skill_schema import enrich_skill_meta, build_manifest
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
)
from inkflow.skill_engine.registry import SkillRegistry


def test_skill_presets():
    """Test preset lookup and normalization."""
    print("=== Test: Skill Presets ===")

    types = list_skill_types()
    assert len(types) == 5, f"Expected 5 skill types, got {len(types)}"
    assert "prophet" in types
    assert "writer" in types
    print(f"  Skill types: {types}")

    preset = get_skill_preset("prophet")
    assert preset["display_name"] == "大纲师"
    assert preset["default_model"] == "deepseek-expert"
    print(f"  Prophet preset: {preset['display_name']} / {preset['default_model']}")

    # Test normalization
    assert normalize_skill_type("Prophet") == "prophet"
    assert normalize_skill_type(None) == "prophet"
    assert normalize_skill_type("unknown") == "prophet"
    print("  Preset normalization: OK")

    print("  PASSED\n")


def test_schema_enrichment():
    """Test metadata enrichment."""
    print("=== Test: Schema Enrichment ===")

    raw_meta = {"skill_type": "prophet", "display_name": "Test Prophet"}
    enriched = enrich_skill_meta(raw_meta, "test-slug")

    assert enriched["schema_version"] == "1"
    assert enriched["slug"] == "test-slug"
    assert enriched["id"] == "inkflow.prophet.test-slug"
    assert enriched["kind"] == "inkflow-skill"
    assert "lifecycle" in enriched
    assert "engine" in enriched
    assert "artifacts" in enriched
    print(f"  Enriched ID: {enriched['id']}")
    print(f"  Engine model: {enriched['engine']['model']}")

    manifest = build_manifest(enriched)
    assert manifest["manifest_version"] == "1"
    assert manifest["id"] == "inkflow.prophet.test-slug"
    print(f"  Manifest ID: {manifest['id']}")

    print("  PASSED\n")


def test_slugify():
    """Test slug generation."""
    print("=== Test: Slugify ===")

    assert slugify("My Prophet") == "my-prophet"
    assert slugify("test_slug") == "test-slug"
    assert slugify("  spaces  ") == "spaces"
    assert slugify("Special!@#Chars") == "special-chars"
    assert slugify("") == "unnamed"
    print("  PASSED\n")


def test_create_and_list():
    """Test skill creation and listing."""
    print("=== Test: Create & List ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)

        meta = {
            "skill_type": "prophet",
            "display_name": "Test Prophet",
            "description": "A test prophet skill",
        }
        skill_dir = create_skill(base, "test-prophet", meta)

        assert skill_dir.exists()
        assert (skill_dir / "agent.py").exists()
        assert (skill_dir / "config.yaml").exists()
        assert (skill_dir / "prompt.md").exists()
        assert (skill_dir / "meta.json").exists()
        assert (skill_dir / "manifest.json").exists()
        assert (skill_dir / "versions").is_dir()
        assert (skill_dir / "knowledge" / "docs").is_dir()
        print(f"  Created: {skill_dir}")

        skills = list_skills(base)
        assert len(skills) == 1
        assert skills[0]["slug"] == "test-prophet"
        assert skills[0]["display_name"] == "Test Prophet"
        print(f"  Listed: {skills[0]['display_name']} {skills[0]['version']}")

    print("  PASSED\n")


def test_update_and_versioning():
    """Test skill update and version management."""
    print("=== Test: Update & Versioning ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)

        meta = {"skill_type": "prophet", "display_name": "Versioned Prophet"}
        skill_dir = create_skill(base, "ver-prophet", meta)

        # Update with a prompt patch
        new_version = update_skill(
            skill_dir,
            prompt_patch="## New Section\n\nThis is a new prompt section.",
        )
        assert new_version == "v2"

        # Check version was archived
        versions = list_versions(skill_dir)
        assert len(versions) == 1
        assert versions[0]["version"] == "v1"
        print(f"  Updated to {new_version}, archived v1")

        # Check prompt was merged
        prompt = (skill_dir / "prompt.md").read_text(encoding="utf-8")
        assert "New Section" in prompt
        print("  Prompt merge: OK")

        # Second update
        update_skill(skill_dir, prompt_patch="## Another Section\n\nMore content.")
        versions = list_versions(skill_dir)
        assert len(versions) == 2
        print(f"  Versions: {[v['version'] for v in versions]}")

    print("  PASSED\n")


def test_rollback():
    """Test version rollback."""
    print("=== Test: Rollback ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)

        meta = {"skill_type": "prophet", "display_name": "Rollback Prophet"}
        skill_dir = create_skill(base, "rb-prophet", meta)

        # Write initial prompt
        (skill_dir / "prompt.md").write_text("## Original\n\nOriginal content.", encoding="utf-8")

        # Update
        update_skill(skill_dir, prompt_patch="## Modified\n\nModified content.")

        # Verify modification
        prompt = (skill_dir / "prompt.md").read_text(encoding="utf-8")
        assert "Modified" in prompt

        # Rollback to v1
        success = rollback(skill_dir, "v1")
        assert success

        # Verify rollback
        prompt = (skill_dir / "prompt.md").read_text(encoding="utf-8")
        assert "Original" in prompt

        # Check meta shows restored version
        with open(skill_dir / "meta.json", "r", encoding="utf-8") as f:
            meta = json.load(f)
        assert "restored" in meta["lifecycle"]["version"]
        print(f"  Rolled back to v1, version now: {meta['lifecycle']['version']}")

    print("  PASSED\n")


def test_registry_discover():
    """Test skill registry discovery and loading."""
    print("=== Test: Registry Discover ===")

    # Use the actual project skills directory
    project_root = Path(__file__).resolve().parent.parent
    skills_dir = project_root / "skills"

    registry = SkillRegistry(base_dir=str(skills_dir))
    count = registry.discover()

    print(f"  Discovered {count} skill(s)")

    if count > 0:
        # Any skill should be discoverable
        first = registry.list()[0]
        print(f"  First skill: {first.skill_type}/{first.slug} ({first.agent_class.__name__})")
        assert issubclass(first.agent_class, BaseSkill)

        # Test instantiation (may fail if no API keys configured)
        try:
            agent = first.instantiate()
            assert agent is not None
            print(f"  Instantiated: {type(agent).__name__}")
        except Exception as e:
            print(f"  Instantiation skipped (expected in test env): {type(e).__name__}")

        for info in registry.list():
            print(f"    [{info.skill_type}] {info.slug} -> {info.agent_class.__name__}")

    print("  PASSED\n")


def test_cleanup():
    """Test old version cleanup."""
    print("=== Test: Cleanup ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)

        meta = {"skill_type": "prophet", "display_name": "Cleanup Prophet"}
        skill_dir = create_skill(base, "clean-prophet", meta)

        # Create multiple versions
        for i in range(12):
            update_skill(skill_dir, prompt_patch=f"## Section {i}\n\nContent {i}")

        versions = list_versions(skill_dir)
        print(f"  Before cleanup: {len(versions)} versions")

        cleanup_old_versions(skill_dir, max_versions=5)

        versions = list_versions(skill_dir)
        print(f"  After cleanup: {len(versions)} versions")
        assert len(versions) <= 5

    print("  PASSED\n")


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  inkflow Skill Engine - Lifecycle Tests")
    print("=" * 50 + "\n")

    test_skill_presets()
    test_schema_enrichment()
    test_slugify()
    test_create_and_list()
    test_update_and_versioning()
    test_rollback()
    test_registry_discover()
    test_cleanup()

    print("=" * 50)
    print("  ALL TESTS PASSED")
    print("=" * 50)
