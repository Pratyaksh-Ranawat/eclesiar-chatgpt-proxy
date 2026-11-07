import os
import re
import hmac
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response, JSONResponse

UPSTREAM = "https://tests-api.eclesiar.com"
API_KEY = os.getenv("ECLESIAR_API_KEY", "").strip()
PROXY_TOKEN = os.getenv("PROXY_ACCESS_TOKEN", "").strip()

app = FastAPI(
    title="Eclesiar API Proxy",
    description="Authenticated, read-only proxy for the Eclesiar API.",
    version="1.1.0",
)

PATH_RE = re.compile(r"^[A-Za-z0-9._~/-]+$")


def check_proxy_token(authorization: Optional[str]) -> None:
    if not PROXY_TOKEN:
        raise HTTPException(status_code=503, detail="Proxy access token is not configured")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not supplied or not hmac.compare_digest(supplied, PROXY_TOKEN):
        raise HTTPException(status_code=401, detail="Use Authorization: Bearer <proxy_token>")


async def eclesiar_get(client: httpx.AsyncClient, path: str, params=None):
    response = await client.get(
        f"{UPSTREAM}/{path}",
        params=params or {},
        headers={"Accept": "application/json", "Authorization": f"Bearer {API_KEY}"},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code", response.status_code) != 200:
        raise HTTPException(status_code=502, detail=f"Eclesiar returned an error for {path}")
    return payload.get("data", [])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "eclesiar-api-proxy"}


@app.get("/public/nation-region-bonuses.json")
async def nation_region_bonuses():
    """Public snapshot of each nation's regions and accumulated regional bonuses."""
    if not API_KEY:
        raise HTTPException(status_code=503, detail="Eclesiar API key is not configured on the server")

    timeout = httpx.Timeout(30.0, connect=8.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            countries = await eclesiar_get(client, "countries")
            if not isinstance(countries, list):
                raise HTTPException(status_code=502, detail="Unexpected countries response format")

            output_countries = []
            total_regions = 0
            all_bonus_types = set()

            for country in countries:
                country_id = country.get("id")
                if country_id is None:
                    continue
                regions = await eclesiar_get(
                    client, "country/regions", {"country_id": country_id}
                )
                if not isinstance(regions, list):
                    raise HTTPException(
                        status_code=502,
                        detail=f"Unexpected regions response for country {country_id}",
                    )

                totals = {}
                output_regions = []
                for region in regions:
                    region_bonuses = region.get("bonus") or []
                    clean_bonuses = []
                    for bonus in region_bonuses:
                        bonus_type = str(bonus.get("type", "UNKNOWN")).upper()
                        value = bonus.get("value", 0)
                        try:
                            numeric_value = float(value)
                        except (TypeError, ValueError):
                            continue
                        totals[bonus_type] = totals.get(bonus_type, 0) + numeric_value
                        all_bonus_types.add(bonus_type)
                        clean_bonuses.append({
                            "type": bonus_type,
                            "value": numeric_value,
                        })

                    output_regions.append({
                        "id": region.get("id"),
                        "name": region.get("name"),
                        "bonus": clean_bonuses,
                    })

                total_regions += len(output_regions)
                output_countries.append({
                    "id": country_id,
                    "name": country.get("name"),
                    "flag": country.get("avatar"),
                    "region_count": len(output_regions),
                    "regions": output_regions,
                    "bonus_totals": dict(sorted(totals.items())),
                })

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Eclesiar API request timed out")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Eclesiar API returned HTTP {exc.response.status_code}",
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach Eclesiar API")

    return JSONResponse(
        content={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Eclesiar API",
            "description": (
                "Each nation's regions and their regional bonuses. bonus_totals "
                "adds the value of every region's bonus by bonus type."
            ),
            "calculation": "For each nation, sum bonus.value for all its regions grouped by bonus.type.",
            "country_count": len(output_countries),
            "region_count": total_regions,
            "bonus_types": sorted(all_bonus_types),
            "countries": output_countries,
        },
        headers={"Cache-Control": "public, max-age=300"},
    )


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
