"""Outline Window — Rolling 5-chapter outline structure.

Maintains a sliding window of chapter outlines that ensures
cross-chapter narrative coherence.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class ChapterOutline(BaseModel):
    """A single chapter's outline entry in the window."""
    model_config = ConfigDict(populate_by_name=True)

    chapter_number: int
    status: str = "pending"  # pending / confirmed / rejected
    chapter_goal: str = ""
    core_conflict: str = ""
    character_arcs: List[str] = Field(default_factory=list)
    key_events: List[str] = Field(default_factory=list)
    info_release: List[str] = Field(default_factory=list)
    foreshadowing_actions: Dict[str, List[str]] = Field(default_factory=lambda: {"to_plant": [], "to_resolve": []})
    emotional_direction: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "ChapterOutline":
        return cls.model_validate(data)

    def is_confirmed(self) -> bool:
        return self.status == "confirmed"

    def is_rejected(self) -> bool:
        return self.status == "rejected"

    def is_pending(self) -> bool:
        return self.status == "pending"


class OutlineWindow(BaseModel):
    """Rolling 5-chapter outline window.

    Covers chapters [current+1, current+5]. After each chapter is generated,
    the window advances: the generated chapter's outline is marked confirmed,
    and a new outline is appended at the end.
    """
    model_config = ConfigDict(populate_by_name=True)

    WINDOW_SIZE: int = Field(default=5, exclude=True)
    outlines: List[ChapterOutline] = Field(default_factory=list)

    def get_outline(self, chapter_number: int) -> Optional[ChapterOutline]:
        """Get outline for a specific chapter, or None if not in window."""
        for o in self.outlines:
            if o.chapter_number == chapter_number:
                return o
        return None

    def get_pending(self) -> List[ChapterOutline]:
        """Get all pending outlines."""
        return [o for o in self.outlines if o.is_pending()]

    def get_all(self) -> List[ChapterOutline]:
        """Get all outlines sorted by chapter number."""
        return sorted(self.outlines, key=lambda o: o.chapter_number)

    def set_outline(self, outline: ChapterOutline):
        """Add or replace an outline entry."""
        for i, o in enumerate(self.outlines):
            if o.chapter_number == outline.chapter_number:
                self.outlines[i] = outline
                return
        self.outlines.append(outline)

    def confirm(self, chapter_number: int):
        """Mark an outline as confirmed after chapter generation."""
        o = self.get_outline(chapter_number)
        if o:
            # Pydantic models are mutable, but we need to ensure update is correctly handled
            o.status = "confirmed"

    def reject(self, chapter_number: int):
        """Mark an outline as rejected."""
        o = self.get_outline(chapter_number)
        if o:
            o.status = "rejected"

    def remove_outline(self, chapter_number: int):
        """删除指定章节的大纲"""
        self.outlines = [
            o for o in self.outlines
            if o.chapter_number != chapter_number
        ]

    def advance(self, current_chapter: int):
        """Advance the window after a chapter is completed.

        - Remove outlines for chapters <= current_chapter that are confirmed
        - Ensure we have outlines covering [current+1, current+5]
        """
        # Remove old confirmed outlines
        self.outlines = [
            o for o in self.outlines
            if o.chapter_number > current_chapter
        ]

    def needs_fill(self, current_chapter: int) -> bool:
        """Check if the window needs new outlines."""
        target_range = range(current_chapter + 1, current_chapter + 1 + 5) # Window size is 5
        existing = {o.chapter_number for o in self.outlines}
        return any(ch not in existing for ch in target_range)

    def get_missing_chapters(self, current_chapter: int) -> List[int]:
        """Get chapter numbers that need outlines."""
        target_range = range(current_chapter + 1, current_chapter + 1 + 5)
        existing = {o.chapter_number for o in self.outlines}
        return [ch for ch in target_range if ch not in existing]

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "OutlineWindow":
        return cls.model_validate(data)
