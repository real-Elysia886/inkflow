"""Pydantic schemas for Skill management endpoints."""

from pydantic import BaseModel, Field
from typing import Optional, Any


class SkillCreate(BaseModel):
    skill_type: str = Field(..., min_length=1)
    slug: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1, le=128000)
    prompt_content: Optional[str] = None
    samples_content: Optional[list[dict[str, Any]]] = None
    agent_code: Optional[str] = None


class SkillUpdate(BaseModel):
    agent_patch: Optional[str] = None
    prompt_patch: Optional[str] = None
    config_patch: Optional[dict[str, Any]] = None


class SkillOut(BaseModel):
    slug: str
    skill_type: str
    name: str
    display_name: str
    description: str
    version: str
    updated_at: str
    corrections_count: int
    path: str


class SkillDetailOut(BaseModel):
    meta: dict[str, Any]
    files: dict[str, str]
    versions: list[dict[str, Any]]


class SkillRunRequest(BaseModel):
    skill_type: str
    slug: Optional[str] = None
    world_state: Optional[dict[str, Any]] = None
    kwargs: dict[str, Any] = Field(default_factory=dict)


class SkillRunResult(BaseModel):
    success: bool
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
