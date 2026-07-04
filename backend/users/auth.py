## Resolve the signed-in Cognito user for profile and broker-credential routes.
##
## In production, API Gateway should attach verified Cognito JWT claims to the
## Lambda event before FastAPI receives the request. This module reads those
## verified claims. A local development fallback can be enabled with
## HELIOS_ALLOW_DEV_AUTH=true, but that fallback should stay disabled in AWS.

import os
from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    email: str
    name: str | None = None


## Return Cognito JWT claims from the API Gateway event attached by Mangum.
## HTTP API JWT authorizers place verified token claims under requestContext.authorizer.jwt.claims.
def _claims_from_api_gateway_event(request: Request):
    event = request.scope.get("aws.event") or {}
    request_context = event.get("requestContext") or {}
    authorizer = request_context.get("authorizer") or {}
    jwt_context = authorizer.get("jwt") or {}
    return jwt_context.get("claims") or {}


## Return a safe local-development user when explicitly enabled.
## This keeps local testing possible without weakening deployed routes by default.
def _dev_user():
    if os.getenv("HELIOS_ALLOW_DEV_AUTH", "").lower() != "true":
        return None

    user_id = os.getenv("HELIOS_DEV_USER_ID", "local-dev-user")
    email = os.getenv("HELIOS_DEV_USER_EMAIL", "local-dev@helios.test")
    name = os.getenv("HELIOS_DEV_USER_NAME", "Local HELIOS User")
    return AuthenticatedUser(user_id=user_id, email=email, name=name)


## Require an authenticated Cognito user and return the stable identity fields HELIOS stores against.
## Profile and credential endpoints call this before reading or writing user-specific broker data.
def require_authenticated_user(request: Request):
    claims = _claims_from_api_gateway_event(request)
    user_id = claims.get("sub")
    email = claims.get("email")
    name = claims.get("name") or claims.get("given_name")

    if user_id and email:
        return AuthenticatedUser(user_id=user_id, email=email, name=name)

    development_user = _dev_user()
    if development_user:
        return development_user

    raise HTTPException(
        status_code=401,
        detail="Authenticated Cognito user is required for profile setup.",
    )
