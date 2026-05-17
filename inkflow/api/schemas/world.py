"""Pydantic schemas for WorldState endpoints."""

from pydantic import BaseModel, Field
from typing import Optional


class CharacterCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    traits: str = ""


class ForeshadowingCreate(BaseModel):
    detail: str = Field(..., min_length=1)
    related_chapter: int = Field(1, ge=1)


class ChapterSummaryCreate(BaseModel):
    chapter_number: int = Field(..., ge=1)
    summary: str = Field(..., min_length=1)


class WorldStateUpdate(BaseModel):
    world_setting: Optional[str] = None
    current_chapter: Optional[int] = Field(None, ge=0)
    setting_templates: Optional[dict[str, str]] = None


class WorldStateSaveRequest(BaseModel):
    file_path: str
