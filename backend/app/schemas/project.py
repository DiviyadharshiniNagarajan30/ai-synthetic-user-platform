from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _strip(v):
    return v.strip() if isinstance(v, str) else v


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    product_description: str | None = Field(default="", max_length=5000)
    target_market: str | None = Field(default="", max_length=2000)
    research_objective: str | None = Field(default="", max_length=3000)
    category: str | None = Field(default=None, max_length=100)

    strip_fields = field_validator("name", "product_description", "target_market",
                         "research_objective", "category", mode="before")(_strip)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v):
        if not v:
            raise ValueError("Project name is required")
        return v


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    product_description: str | None = Field(default=None, max_length=5000)
    target_market: str | None = Field(default=None, max_length=2000)
    research_objective: str | None = Field(default=None, max_length=3000)
    category: str | None = Field(default=None, max_length=100)

    strip_fields = field_validator("name", "product_description", "target_market",
                         "research_objective", "category", mode="before")(_strip)


class ProjectResponse(ProjectCreate):
    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)
