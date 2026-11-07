import os
import re
import hmac
from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response

UPSTREAM = "https://tests-api.eclesiar.com"
API_KEY = os.getenv("ECLESIAR_API_KEY", "").strip()
PROXY_TOKEN = os.getenv("PROXY_ACCESS_TOKEN", "").strip()

app = FastAPI(
    title="Eclesiar API Proxy",
    description="Authenticated, read-only proxy for the Eclesiar API.",
    version="1.0.0",
)

PATH_RE = re.compile(r"^[A-Za-z0-9._~/-]+$")


def check_proxy_token(authorization: Optional[str]) -> None:
    if not PROXY_TOKEN:
        raise HTTPException(status_code=503, detail="Proxy access token is not configured")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not supplied or not hmac.compare_digest(supplied, PROXY_TOKEN):
        raise HTTPException(status_code=401, detail="Use Authorization: Bearer <proxy_token>")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "eclesiar-api-proxy"}


@app.get("/api/{endpoint_path:path}")
async def proxy_get(
    endpoint_path: str,
    request: Request,
    authorization: Optional[str] = Header(default=None),
):
    check_proxy_token(authorization)

    if (
        not endpoint_path
        or len(endpoint_path) > 500
        or not PATH_RE.fullmatch(endpoint_path)
        or ".." in endpoint_path
        or endpoint_path.startswith("/")
    ):
        raise HTTPException(status_code=400, detail="Invalid API path")

    if not API_KEY:
        raise HTTPException(status_code=503, detail="Eclesiar API key is not configured on the server")

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }
    params = list(request.query_params.multi_items())

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=8.0),
            follow_redirects=False,
        ) as client:
            upstream = await client.get(
                f"{UPSTREAM}/{endpoint_path}",
                params=params,
                headers=headers,
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Eclesiar API request timed out")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach Eclesiar API")

    content_type = upstream.headers.get("content-type", "application/json").split(";")[0]
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=content_type,
    )
