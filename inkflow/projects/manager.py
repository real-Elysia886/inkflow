"""Project Manager - Manages multiple novel projects.

Each project has its own:
- world_state.json (characters, relationships, timeline, etc.)
- chapters/ directory (generated chapter files)
- feedback.json (human feedback history)
- rag_index/ (text chunks for retrieval)
"""

import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from inkflow.memory.world_state import WorldState
from inkflow.utils.atomic_io import write_json_atomic

PROJECTS_DIR = Path(__file__).parent.parent.parent / "data" / "projects"


class Project:
    """A novel project with its own world state and chapters."""

    def __init__(self, project_id: str, name: str = "", description: str = ""):
        self.project_id = project_id
        self.name = name or project_id
        self.description = description
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.dir = PROJECTS_DIR / project_id
        self.world_state = WorldState()
        self.skill_map: Dict[str, str] = {}  # role_type -> slug
        self._chapters: List[Dict[str, Any]] = []
        self._feedback: List[Dict[str, Any]] = []
        self._chapters_loaded = False
        self._feedback_loaded = False

    @property
    def chapters_dir(self) -> Path:
        return self.dir / "chapters"

    @property
    def world_file(self) -> Path:
        return self.dir / "world_state.json"

    @property
    def feedback_file(self) -> Path:
        return self.dir / "feedback.json"

    @property
    def meta_file(self) -> Path:
        return self.dir / "meta.json"

    def create(self):
        """Create project on disk."""
        self.dir.mkdir(parents=True, exist_ok=True)
        self.chapters_dir.mkdir(exist_ok=True)
        self._save_meta()
        self.world_state.save(str(self.world_file))
        self._save_feedback()

    def load(self):
        """Load project metadata and world state from disk. Chapters/feedback are lazy-loaded."""
        if not self.dir.exists():
            raise FileNotFoundError(f"Project '{self.project_id}' not found")

        meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
        self.name = meta.get("name", self.project_id)
        self.description = meta.get("description", "")
        self.created_at = meta.get("created_at", "")
        self.skill_map = meta.get("skill_map", {})

        if self.world_file.exists():
            self.world_state.load(str(self.world_file))

        # Lazy-load: only load chapters/feedback when accessed
        self._chapters_loaded = False
        self._feedback_loaded = False

    def save(self):
        """Save project to disk."""
        self.dir.mkdir(parents=True, exist_ok=True)
        self.chapters_dir.mkdir(exist_ok=True)
        self._save_meta()
        self.world_state.save(str(self.world_file))
        if self._feedback_loaded:
            self._save_feedback()

    def add_chapter(self, chapter_data: Dict[str, Any]):
        """Persist a generated chapter.

        Writes the chapter file and updates ``meta.json`` (chapter_count). The
        caller is responsible for persisting ``world_state`` separately
        (typically via ``ProjectManager.save_world_state``) so we avoid
        rewriting the full world JSON for every chapter.
        """
        ch_num = chapter_data.get("chapter_number", len(self.chapters) + 1)
        chapter_data["saved_at"] = datetime.now(timezone.utc).isoformat()

        # Save chapter file atomically
        ch_file = self.chapters_dir / f"chapter_{ch_num:03d}.json"
        self.chapters_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(ch_file, chapter_data)

        # Update in-memory list
        self.chapters = [c for c in self.chapters if c.get("chapter_number") != ch_num]
        self.chapters.append(chapter_data)
        self.chapters.sort(key=lambda c: c.get("chapter_number", 0))

        # Refresh meta only (chapter_count changed). World state stays untouched here.
        self._save_meta()

    def _ensure_chapters_loaded(self):
        if not self._chapters_loaded:
            self._load_chapters()
            self._chapters_loaded = True

    def _ensure_feedback_loaded(self):
        if not self._feedback_loaded:
            self._load_feedback()
            self._feedback_loaded = True

    @property
    def chapters(self) -> List[Dict[str, Any]]:
        self._ensure_chapters_loaded()
        return self._chapters

    @chapters.setter
    def chapters(self, value: List[Dict[str, Any]]):
        self._chapters = value

    @property
    def feedback(self) -> List[Dict[str, Any]]:
        self._ensure_feedback_loaded()
        return self._feedback

    @feedback.setter
    def feedback(self, value: List[Dict[str, Any]]):
        self._feedback = value

    def get_chapter(self, chapter_number: int) -> Optional[Dict[str, Any]]:
        """Get a specific chapter."""
        for ch in self.chapters:
            if ch.get("chapter_number") == chapter_number:
                return ch
        return None

    def update_chapter_text(self, chapter_number: int, new_text: str):
        """Update chapter text (after human editing)."""
        ch = self.get_chapter(chapter_number)
        if ch:
            ch["final_text"] = new_text
            ch["edited_by_human"] = True
            ch["last_edited"] = datetime.now(timezone.utc).isoformat()
            ch_file = self.chapters_dir / f"chapter_{chapter_number:03d}.json"
            write_json_atomic(ch_file, ch)

    def delete_chapter(self, chapter_number: int) -> bool:
        """删除指定章节及其文件、trace 与 checkpoint。"""
        # 1. 章节文件
        ch_file = self.chapters_dir / f"chapter_{chapter_number:03d}.json"
        if ch_file.exists():
            ch_file.unlink()

        # 2. 内存列表
        self.chapters = [c for c in self.chapters if c.get("chapter_number") != chapter_number]

        # 3. 反馈
        self.feedback = [f for f in self.feedback if f.get("chapter_number") != chapter_number]
        self._save_feedback()

        # 4. trace 目录（按章节号组织）
        trace_dir = self.dir / "traces" / f"ch{chapter_number:03d}"
        if trace_dir.exists():
            shutil.rmtree(trace_dir, ignore_errors=True)

        # 5. checkpoint：按章节号没法直接对应 job，但可以按内容判断
        # 策略：保守起见，仅删除最后一次 stage 与该章节匹配的 checkpoint。
        cp_dir = self.dir / "checkpoints"
        if cp_dir.exists():
            for cp_file in cp_dir.glob("job_*.json"):
                try:
                    data = json.loads(cp_file.read_text(encoding="utf-8"))
                    cp_chapter = (data.get("data") or {}).get("chapter_number")
                    if cp_chapter == chapter_number:
                        cp_file.unlink()
                except (json.JSONDecodeError, OSError):
                    continue

        # 6. 更新世界状态并落盘
        self.world_state.remove_chapter_meta(chapter_number)
        self.world_state.outline_window.remove_outline(chapter_number)
        self.save()

        return True

    def add_feedback(self, chapter_number: int, rating: int,
                     comment: str = "", annotations: list = None):
        """Add human feedback for a chapter."""
        fb = {
            "chapter_number": chapter_number,
            "rating": rating,
            "comment": comment,
            "annotations": annotations or [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.feedback.append(fb)
        self._save_feedback()

    def get_recent_feedback(self, n: int = 10) -> List[Dict]:
        """Get recent feedback for context."""
        return self.feedback[-n:]

    def delete(self):
        """Delete project from disk."""
        if self.dir.exists():
            shutil.rmtree(self.dir)

    def _save_meta(self):
        # 避免触发懒加载：如果章节未加载，从磁盘计算章节数
        if self._chapters_loaded:
            chapter_count = len(self._chapters)
        elif self.chapters_dir.exists():
            chapter_count = len(list(self.chapters_dir.glob("chapter_*.json")))
        else:
            chapter_count = 0

        meta = {
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "chapter_count": chapter_count,
            "skill_map": self.skill_map,
        }
        write_json_atomic(self.meta_file, meta)

    def _save_feedback(self):
        write_json_atomic(self.feedback_file, self.feedback)

    def _load_chapters(self):
        self._chapters = []
        if not self.chapters_dir.exists():
            return
        for f in sorted(self.chapters_dir.glob("chapter_*.json")):
            try:
                ch = json.loads(f.read_text(encoding="utf-8"))
                self._chapters.append(ch)
            except (json.JSONDecodeError, OSError):
                continue

    def _load_feedback(self):
        if self.feedback_file.exists():
            try:
                self.feedback = json.loads(self.feedback_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.feedback = []


class ProjectManager:
    """Manages all projects with in-memory caching."""

    _project_cache: Dict[str, Project] = {}
    _projects_list_cache: Optional[List[Dict[str, Any]]] = None
    _cache_lock = threading.Lock()

    def __init__(self):
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    def list_projects(self) -> List[Dict[str, Any]]:
        """List all projects with caching."""
        with self._cache_lock:
            if self._projects_list_cache is not None:
                return self._projects_list_cache

        # Build outside lock to avoid blocking other operations
        projects = []
        for d in sorted(PROJECTS_DIR.iterdir()):
            if d.is_dir() and (d / "meta.json").exists():
                try:
                    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                    projects.append(meta)
                except (json.JSONDecodeError, OSError):
                    continue

        with self._cache_lock:
            self._projects_list_cache = projects
        return projects

    def _invalidate_list_cache(self):
        with self._cache_lock:
            self._projects_list_cache = None

    def get_project(self, project_id: str) -> Project:
        """Load a project by ID with caching."""
        with self._cache_lock:
            if project_id in self._project_cache:
                return self._project_cache[project_id]
            # Create and load within the same lock to prevent TOCTOU
            p = Project(project_id)
            p.load()
            self._project_cache[project_id] = p
            return p

    def create_project(self, project_id: str, name: str = "",
                       description: str = "") -> Project:
        """Create a new project."""
        import re
        project_id = re.sub(r'[^\w\-]', '_', project_id.strip())
        if not project_id:
            project_id = f"project_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        if (PROJECTS_DIR / project_id).exists():
            raise ValueError(f"Project '{project_id}' already exists")

        p = Project(project_id, name, description)
        p.create()

        with self._cache_lock:
            self._project_cache[project_id] = p
        self._invalidate_list_cache()
        return p

    def delete_project(self, project_id: str):
        """Delete a project and clear from cache."""
        p = Project(project_id)
        if not p.dir.exists():
            raise FileNotFoundError(f"Project '{project_id}' not found")

        # Delete from disk first, then remove from cache
        p.delete()
        with self._cache_lock:
            if project_id in self._project_cache:
                del self._project_cache[project_id]
        self._invalidate_list_cache()

    def get_or_create_default(self) -> Project:
        """Get or create the default project."""
        try:
            return self.get_project("default")
        except FileNotFoundError:
            # Directory exists but meta.json missing — clean up and recreate
            default_dir = PROJECTS_DIR / "default"
            if default_dir.exists():
                shutil.rmtree(default_dir)
            return self.create_project("default", "默认项目", "默认的小说创作项目")

    def get_world_state(self, project_id: str) -> WorldState:
        return self.get_project(project_id).world_state

    def save_world_state(self, project_id: str, world_state: WorldState):
        p = self.get_project(project_id)
        p.world_state = world_state
        p.save()

    def invalidate_cache(self, project_id: str):
        """Remove a project from the in-memory cache (forces reload on next access)."""
        with self._cache_lock:
            self._project_cache.pop(project_id, None)
        self._invalidate_list_cache()

    def save_chapter(self, project_id: str, chapter_number: int, text: str):
        p = self.get_project(project_id)
        p.update_chapter_text(chapter_number, text)
