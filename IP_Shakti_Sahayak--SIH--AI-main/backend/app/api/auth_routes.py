from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from ..auth import Identity, auth_service, require_role
from ..schemas import IdentityResponse, TokenResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenResponse)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> TokenResponse:
    """Exchange operator credentials for a bearer token.

    The standard OAuth2 password form rather than a bespoke JSON body, so
    the "Authorize" button in /docs works against the real login and an
    operator can try a role out without a frontend.
    """
    identity = auth_service.authenticate(form.username, form.password)
    if identity is None:
        # One message for both "no such user" and "wrong password": which
        # of the two it was is exactly what an attacker is trying to learn.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, expires_in = auth_service.issue_token(identity)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        username=identity.username,
        role=identity.role,
    )


@router.get("/me", response_model=IdentityResponse)
def me(
    identity: Annotated[Identity, Depends(require_role("USER"))],
) -> IdentityResponse:
    """Who the presented token belongs to.

    Gated at USER — the weakest role — so this answers "is my token still
    valid" for any signed-in caller. The frontend calls it on load to
    decide whether a stored token still opens the reviewer console, rather
    than discovering it has expired at the moment someone clicks approve.
    """
    return IdentityResponse(username=identity.username, role=identity.role)
