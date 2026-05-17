"""Pydantic schemas for LLM configuration endpoints."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class ProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    base_url: str = Field(..., min_length=1)
    api_key_env: str = Field(..., min_length=1)
    api_key: Optional[str] = Field(None, description="Direct API key (will be saved to .env)")


class ProviderOut(BaseModel):
    name: str
    base_url: str
    api_key_env: str
    has_key: bool


class RoleRouteCreate(BaseModel):
    role_name: str = Field(..., min_length=1, max_length=50)
    provider: str = Field(..., min_length=1)
    model_name: str = Field(..., min_length=1)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(2048, ge=1, le=128000)


class RoleRouteOut(BaseModel):
    role_name: str
    provider: str
    model_name: str
    temperature: float
    max_tokens: int


class LLMSettingsOut(BaseModel):
    providers: list[ProviderOut]
    role_routing: list[RoleRouteOut]
    default: RoleRouteOut
    active_skills: List[Dict[str, Any]] = []
