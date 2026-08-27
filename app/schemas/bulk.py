from pydantic import BaseModel, Field


class BulkActionRequest(BaseModel):
    ids: list[int] = Field(min_length=1)
    action: str
    role_id: str | None = None
    replace_skill: bool = False


class BulkFailureItem(BaseModel):
    id: int
    detail: str


class BulkActionResponse(BaseModel):
    ok: bool
    action: str
    succeeded: list[int]
    failed: list[BulkFailureItem]
