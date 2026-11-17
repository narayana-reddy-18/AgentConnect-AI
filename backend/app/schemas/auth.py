from pydantic import BaseModel, ConfigDict


class UserRead(BaseModel):
    id: int
    email: str | None
    email_verified: bool
    name: str | None

    model_config = ConfigDict(from_attributes=True)


class CsrfTokenRead(BaseModel):
    csrf_token: str
