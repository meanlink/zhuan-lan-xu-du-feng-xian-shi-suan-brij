from pydantic import BaseModel, Field
class JobInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    dataset_id: int
    params: dict = Field(default_factory=dict)
    # Version of the identity ledger shown to the user when submitting. Omit to
    # accept whatever complete version is current at creation time.
    expected_identity_version: int | None = Field(default=None, ge=0)
    # Retry-safe create: the same key returns the experiment already created.
    operation_key: str | None = Field(default=None, max_length=160)
