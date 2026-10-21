from pydantic import BaseModel, ConfigDict, Field


class BehaviorCreate(BaseModel):
    persona_id: int

    expense_tracking: int = Field(ge=1, le=5)
    saving_habit: int = Field(ge=1, le=5)
    shopping_frequency: int = Field(ge=1, le=5)
    impulse_buying: int = Field(ge=1, le=5)
    budget_awareness: int = Field(ge=1, le=5)
    technology_usage: int = Field(ge=1, le=5)


class BehaviorResponse(BehaviorCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)