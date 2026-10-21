from typing import Annotated

from fastapi import Header, HTTPException

# Prototype!!! Only depends on the header without verification. Replace with real authentication
# (e.g., signed header with HMAC like in SupoClip, or JWT).
def get_current_user_id(
    x_user_id: Annotated[str | None, Header()] = None,
) -> str:
    if not x_user_id or not x_user_id.strip():
        raise HTTPException(status_code=401, detail="Missing X-User-Id header")
    return x_user_id.strip()