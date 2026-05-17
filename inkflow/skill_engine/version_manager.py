"""Skill version lifecycle management.

Handles version archiving, rollback, and cleanup of archived versions.
Mirrors dot-skill's version_manager but adapted for inkflow's skill structure.
"""

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

from inkflow.skill_engine.skill_schema import PRIMARY_ARTIFACTS

MAX_VERSIONS = 10


def list_versions(skill_dir: Path) -> List[Dict]:
    """List all archived versions for a skill."""
    versions_dir = skill_dir / "versions"
    if not versions_dir.exists():
        return []

    results = []
    for d in sorted(versions_dir.iterdir()):
        if d.is_dir():
            mtime = datetime.fromtimestamp(d.stat().st_mtime, tz=timezone.utc)
            files = [f.name for f in d.iterdir()] if d.exists() else []
            results.append({
                "version": d.name,
                "archived_at": mtime.strftime("%Y-%m-%d %H:%M"),
                "files": files,
                "path": str(d),
            })
    return results


def backup_artifacts(skill_dir: Path, backup_dir: Path) -> None:
    """Copy all primary artifacts from skill_dir into backup_dir."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    for fname in PRIMARY_ARTIFACTS:
        src = skill_dir / fname
        if src.exists():
            shutil.copy2(src, backup_dir / fname)


def backup_current_version(skill_dir: Path) -> bool:
    """Archive current artifacts under versions/{current_version}/."""
    meta_file = skill_dir / "meta.json"
    if not meta_file.exists():
        print(f"Error: meta.json not found in {skill_dir}", file=sys.stderr)
        return False

    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)

    version = meta.get("lifecycle", {}).get("version", meta.get("version", "v1"))
    backup_dir = skill_dir / "versions" / version
    backup_artifacts(skill_dir, backup_dir)
    print(f"Backed up version {version} -> {backup_dir}")
    return True


def rollback(skill_dir: Path, target_version: str) -> bool:
    """Restore a previously archived version."""
    version_dir = skill_dir / "versions" / target_version
    if not version_dir.exists():
        print(f"Error: version '{target_version}' not found at {version_dir}", file=sys.stderr)
        return False

    meta_src = version_dir / "meta.json"
    if not meta_src.exists():
        print(f"Error: meta.json not found in version '{target_version}'", file=sys.stderr)
        return False

    # Backup current state before rollback
    with open(skill_dir / "meta.json", "r", encoding="utf-8") as f:
        current_meta = json.load(f)
    current_version = current_meta.get("lifecycle", {}).get("version", current_meta.get("version", "v1"))
    pre_rollback_dir = skill_dir / "versions" / f"{current_version}_before_rollback"
    backup_artifacts(skill_dir, pre_rollback_dir)

    # Restore each artifact
    for fname in PRIMARY_ARTIFACTS:
        src = version_dir / fname
        if src.exists():
            shutil.copy2(src, skill_dir / fname)

    # Update meta.json with rollback info
    with open(skill_dir / "meta.json", "r", encoding="utf-8") as f:
        meta = json.load(f)

    meta.setdefault("lifecycle", {})
    meta["lifecycle"]["version"] = f"{target_version}_restored"
    meta["lifecycle"]["updated_at"] = datetime.now(timezone.utc).isoformat()
    meta["lifecycle"]["rollback_from"] = target_version

    with open(skill_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"Rolled back to {target_version} (pre-rollback saved as {pre_rollback_dir.name})")
    return True


def cleanup_old_versions(skill_dir: Path, max_versions: int = MAX_VERSIONS) -> None:
    """Remove archived versions beyond the retention limit."""
    versions_dir = skill_dir / "versions"
    if not versions_dir.exists():
        return

    dirs = sorted(
        [d for d in versions_dir.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )

    for old_dir in dirs[max_versions:]:
        shutil.rmtree(old_dir)
        print(f"Cleaned up old version: {old_dir.name}")
