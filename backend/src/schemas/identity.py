from pydantic import BaseModel, Field


class MergeInput(BaseModel):
    numbers: list[str] = Field(min_length=2, max_length=200)
    expected_version: int = Field(ge=0)
    reason: str = Field(default='', max_length=300)
    operation_key: str | None = Field(default=None, max_length=120)


class SplitInput(BaseModel):
    number: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=0)
    reason: str = Field(default='', max_length=300)
    operation_key: str | None = Field(default=None, max_length=120)


class RegisterInput(BaseModel):
    numbers: list[str] = Field(min_length=1, max_length=500)
    reason: str = Field(default='', max_length=300)
