"""Skill Registry - dynamic discovery and loading of inkflow skills.

The registry scans the skills/ directory for agent.py files, dynamically
imports them, and provides a lookup interface to get skill instances by name.

Usage:
    registry = SkillRegistry.get_default()  # process-wide singleton
    registry.discover()                     # idempotent (mtime-aware)
    agent = registry.get("prophet")         # get a ProphetAgent instance
    agent = registry.get("prophet", "custom-slug")  # specific instance
    registry.list()                         # list all discovered skills
"""

import importlib.util
import json
import sys
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List, Type

from inkflow.core.base_skill import BaseSkill
from inkflow.skill_engine.skill_presets import resolve_storage_root


class SkillInfo:
    """Metadata about a discovered skill."""

    def __init__(
        self,
        skill_type: str,
        slug: str,
        agent_class: Type[BaseSkill],
        skill_dir: Path,
        meta: Dict[str, Any],
    ):
        self.skill_type = skill_type
        self.slug = slug
        self.agent_class = agent_class
        self.skill_dir = skill_dir
        self.meta = meta
        self.display_name = meta.get("display_name", slug)
        self.description = meta.get("description", "")

    def __repr__(self):
        return f"<SkillInfo: {self.skill_type}/{self.slug} ({self.display_name})>"

    def instantiate(self, **kwargs) -> BaseSkill:
        """Create an instance of this skill's agent."""
        return self.agent_class(skill_path=str(self.skill_dir), **kwargs)


class SkillRegistry:
    """Dynamic skill discovery and loading registry."""

    # Process-wide singleton machinery (used by ChapterPipeline / API routers).
    _default_instance: Optional["SkillRegistry"] = None
    _default_lock = threading.Lock()

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = resolve_storage_root(base_dir=base_dir)
        self._skills: Dict[str, SkillInfo] = {}  # key: "type/slug"
        self._by_type: Dict[str, List[SkillInfo]] = {}
        # Last seen mtime per agent.py — used to skip rediscovery when nothing
        # has changed on disk. Populated by discover().
        self._mtimes: Dict[str, float] = {}

    @classmethod
    def get_default(cls) -> "SkillRegistry":
        """Return a process-wide registry, performing discovery if needed.

        Subsequent calls reuse the same instance. Use ``invalidate()`` to drop
        the singleton (e.g. after creating/removing a skill via the API).
        """
        with cls._default_lock:
            if cls._default_instance is None:
                cls._default_instance = cls()
                cls._default_instance.discover()
            else:
                # Cheap mtime sweep — only reloads when files actually changed.
                cls._default_instance.discover_if_stale()
            return cls._default_instance

    @classmethod
    def invalidate_default(cls):
        """Force the next ``get_default()`` call to rebuild the registry."""
        with cls._default_lock:
            cls._default_instance = None

    def _scan_agent_files(self) -> List[Path]:
        """Enumerate every agent.py path the registry would load."""
        files: List[Path] = []
        if not self.base_dir.exists():
            return files
        for entry in sorted(self.base_dir.iterdir()):
            if not entry.is_dir():
                continue
            agent_file = entry / "agent.py"
            if agent_file.exists():
                files.append(agent_file)
            for skill_dir in sorted(entry.iterdir()):
                if not skill_dir.is_dir():
                    continue
                a = skill_dir / "agent.py"
                if a.exists():
                    files.append(a)
        return files

    def discover_if_stale(self) -> bool:
        """Re-run ``discover()`` only if any agent.py mtime changed.

        Returns True when a rediscovery actually happened.
        """
        current: Dict[str, float] = {}
        for f in self._scan_agent_files():
            try:
                current[str(f)] = f.stat().st_mtime
            except OSError:
                continue
        # Same set of files and same mtimes → nothing to do.
        if current == self._mtimes and self._skills:
            return False
        self.discover()
        return True

    def discover(self) -> int:
        """Scan skills/ directory and load all valid skill agents.

        Supports both:
        - One-level: skills/{slug}/agent.py
        - Two-level: skills/{type}/{slug}/agent.py

        Returns:
            Number of skills discovered.
        """
        self._skills.clear()
        self._by_type.clear()
        self._mtimes.clear()

        if not self.base_dir.exists():
            return 0

        count = 0
        for entry in sorted(self.base_dir.iterdir()):
            if not entry.is_dir():
                continue

            # Case A: One-level skill (e.g. skills/editor/agent.py)
            agent_file = entry / "agent.py"
            if agent_file.exists():
                if self._load_and_register(entry, entry.name, entry.name):
                    count += 1
                self._record_mtime(agent_file)

            # Case B: Two-level skill container (e.g. skills/editor/my-slug/agent.py)
            for skill_dir in sorted(entry.iterdir()):
                if not skill_dir.is_dir():
                    continue
                agent_file = skill_dir / "agent.py"
                if agent_file.exists():
                    if self._load_and_register(skill_dir, entry.name, skill_dir.name):
                        count += 1
                    self._record_mtime(agent_file)

        return count

    def _record_mtime(self, agent_file: Path) -> None:
        try:
            self._mtimes[str(agent_file)] = agent_file.stat().st_mtime
        except OSError:
            pass

    def _load_and_register(self, skill_dir: Path, default_type: str, default_slug: str) -> bool:
        """Internal helper to load and register a skill directory."""
        agent_file = skill_dir / "agent.py"
        meta_file = skill_dir / "meta.json"
        
        # Load metadata
        meta = {}
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except (json.JSONDecodeError, OSError):
                meta = {}

        skill_type = meta.get("skill_type", default_type)
        slug = meta.get("slug", default_slug)

        # Dynamically import the agent module
        agent_class = self._load_agent_class(agent_file, slug)
        if agent_class is None:
            return False

        info = SkillInfo(
            skill_type=skill_type,
            slug=slug,
            agent_class=agent_class,
            skill_dir=skill_dir,
            meta=meta,
        )

        key = f"{skill_type}/{slug}"
        self._skills[key] = info
        self._by_type.setdefault(skill_type, []).append(info)
        return True

    def _load_agent_class(self, agent_file: Path, slug: str) -> Optional[Type[BaseSkill]]:
        """Dynamically import agent.py and find the BaseSkill subclass."""
        # Use a slug-derived module name. Re-importing the same skill (e.g.
        # after a distillation rewrite) would otherwise hit the cached module
        # in sys.modules and silently keep running stale code, so we evict
        # it first.
        module_name = f"inkflow.skills.{slug}.agent"
        sys.modules.pop(module_name, None)

        try:
            spec = importlib.util.spec_from_file_location(module_name, str(agent_file))
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as e:
            import traceback
            print(f"CRITICAL: Failed to load skill agent at {agent_file}: {e}")
            print(traceback.format_exc())
            # Keep sys.modules clean on import failure.
            sys.modules.pop(module_name, None)
            return None

        # Find the first class that is a BaseSkill subclass
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseSkill)
                and attr is not BaseSkill
            ):
                return attr

        return None

    def get(self, skill_type: str, slug: Optional[str] = None) -> Optional[SkillInfo]:
        """Get a skill by type and optional slug.

        If slug is None and there's only one skill of that type, return it.
        If slug is None and there are multiple, return None (ambiguous).
        """
        skills = self._by_type.get(skill_type, [])
        if not skills:
            return None

        if slug is None:
            if len(skills) == 1:
                return skills[0]
            return None  # ambiguous

        key = f"{skill_type}/{slug}"
        return self._skills.get(key)

    def list(self) -> List[SkillInfo]:
        """Return all discovered skills."""
        return list(self._skills.values())

    def get_preferred(self, skill_type: str) -> Optional[SkillInfo]:
        """Get the preferred skill for a type: first non-base skill, or base as fallback.

        A skill is considered "base" when its slug equals the skill_type
        (e.g. skills/editor/agent.py → slug="editor", skill_type="editor").
        """
        skills = self._by_type.get(skill_type, [])
        if not skills:
            return None
        # Prefer non-base (distilled/custom) skills
        for s in skills:
            if s.slug != skill_type:
                return s
        # Fall back to base
        return skills[0]

    def list_by_type(self, skill_type: str) -> List[SkillInfo]:
        """Return all skills of a given type."""
        return self._by_type.get(skill_type, [])

    def types(self) -> List[str]:
        """Return all discovered skill types."""
        return list(self._by_type.keys())

    def instantiate(self, skill_type: str, slug: Optional[str] = None, **kwargs) -> Optional[BaseSkill]:
        """Convenience: discover + get + instantiate in one call."""
        info = self.get(skill_type, slug)
        if info is None:
            return None
        return info.instantiate(**kwargs)
