import os
from typing import List, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator

OSRM_BASEURL = os.getenv("OSRM_BASEURL", "http://127.0.0.1:5001")

app = FastAPI(title="Realtime Proxy OSRM", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TrackRequest(BaseModel):
    coordinates: List[List[float]] = Field(..., description="[lon, lat] em ordem", min_items=2)
    profile: Literal["driving", "driving-hgv", "walking", "cycling"] = "driving"
    overview: Literal["simplified", "full", "false"] = "full"
    geometries: Literal["polyline", "polyline6", "geojson"] = "geojson"
    steps: bool = False
    annotations: Optional[Literal["false", "true", "nodes", "distance", "duration", "speed", "datasources", "weight"]] = "false"

    @validator("coordinates", each_item=True)
    def check_coord(cls, v):
        if not isinstance(v, list) or len(v) != 2:
            raise ValueError("Cada coordenada deve ser [lon, lat]")
        lon, lat = v
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise ValueError("Coordenadas fora do intervalo permitido")
        return v

@app.get("/ping")
async def ping():
    return {"msg": "pong"}

@app.get("/healthz")
async def healthz():
    url = f"{OSRM_BASEURL}/nearest/v1/driving/0,0"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(url)
            ok = r.status_code == 200
    except Exception:
        ok = False
    return {"ok": ok, "osrm": OSRM_BASEURL}

@app.post("/api/track")
async def track(body: TrackRequest):
    coords = ";".join([f"{lon},{lat}" for lon, lat in body.coordinates])
    url = (
        f"{OSRM_BASEURL}/route/v1/{body.profile}/{coords}"
        f"?overview={body.overview}&geometries={body.geometries}"
        f"&steps={'true' if body.steps else 'false'}"
        f"&annotations={body.annotations if body.annotations else 'false'}"
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Erro ao contatar OSRM: {e}") from e

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    data = resp.json()
    return {
        "source": "osrm",
        "osrm_url": url,
        "waypoints": data.get("waypoints"),
        "routes": data.get("routes"),
        "code": data.get("code", "Ok"),
    }
