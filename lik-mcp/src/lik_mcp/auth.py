from typing import Protocol

from pydantic import BaseModel


class Identity(BaseModel):
    """A verified caller. `email` is the authorization claim; never self-asserted in prod."""

    email: str
    groups: list[str] = []


class Verifier(Protocol):
    def verify(self, token: str | None) -> Identity: ...


class StubVerifier:
    """Test/dev only. Treats the token as the caller's email and never validates it.
    The real GoogleOIDCVerifier is a later, drop-in implementation with the same
    interface, so tool signatures don't change when it lands."""

    def __init__(self, default_email: str = "service@navapbc.com", groups: list[str] | None = None):
        self.default_email = default_email
        self.groups = groups or []

    def verify(self, token: str | None) -> Identity:
        return Identity(email=token or self.default_email, groups=list(self.groups))


class FailClosedVerifier:
    """Default outside dev/test: refuse everything. Prevents the stub from silently
    authenticating callers in a real deployment before OIDC exists."""

    def verify(self, token: str | None) -> Identity:
        raise PermissionError(
            "No real verifier configured (LIK_ENV is not dev/test). Refusing to authenticate."
        )
