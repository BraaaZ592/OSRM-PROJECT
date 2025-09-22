import json
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import sys

import tkinter as tk
from tkinter import filedialog, messagebox

import requests

VALHALLA_BASE = "http://localhost:8002"
VALHALLA_ROUTE = VALHALLA_BASE.rstrip("/") + "/route"
MAX_VIAS = 10 

ALLOWED_ROAD_CLASSES = {
    "motorway", "trunk", "primary", "secondary",
    "tertiary", "unclassified", "residential",
}

DISALLOWED_USE = {
    "driveway", "parking_aisle", "footway", "path",
    "steps", "pedestrian", "alley",
}

LOCATE_MAX_DIST_M = 25

LOCATE_TIMEOUT = 8

def is_point_on_valid_road(lat: float, lon: float) -> bool:
    url = VALHALLA_BASE.rstrip("/") + "/locate"
    payload = {
        "locations": [{
            "lat": lat,
            "lon": lon,
            "radius": LOCATE_MAX_DIST_M,
            "search_filter": {
                "min_road_class": "residential",
                "max_road_class": "motorway"
            }
        }]
    }
    try:
        r = requests.post(url, json=payload, timeout=LOCATE_TIMEOUT)
        if r.status_code != 200:
            return False
        data = r.json()
        locs = data.get("locations") or []
        if not locs:
            return False
        corr = (locs[0].get("correlation") or {})
        edges = corr.get("edges") or []
        if not edges:
            return False
        best = min(
            edges, key=lambda e: float(e.get("distance", 1e9))
        )
        dist = float(best.get("distance", 1e9))
        if dist > LOCATE_MAX_DIST_M:
            return False
        road_class = str(best.get("road_class", ""))
        use = str(best.get("use", ""))
        if road_class not in ALLOWED_ROAD_CLASSES:
            return False
        if use in DISALLOWED_USE:
            return False
        return True
    except Exception:
        return False

def decode_polyline6(polyline: str) -> List[Tuple[float, float]]:
    index, lat, lon = 0, 0, 0
    coordinates: List[Tuple[float, float]] = []
    while index < len(polyline):
        for _ in range(2):
            shift = 0
            result = 0
            while True:
                if index >= len(polyline):
                    break
                b = ord(polyline[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if _ == 0:
                lat += delta
            else:
                lon += delta
        coordinates.append((lat / 1e6, lon / 1e6))
    return coordinates

def _from_array_of_dicts(data: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
        out: List[Dict[str, Any]] = []
        for p in data:
            if "lat" in p and "lon" in p:
                item = {"lat": float(p["lat"]), "lon": float(p["lon"])}
                if "time" in p:
                    item["time"] = int(p["time"])
                out.append(item)
            else:
                return None
        return out
    return None

def _from_erictech_schema(data: Any) -> Optional[List[Dict[str, Any]]]:
    try:
        route = data["track"]["route"]
        if not isinstance(route, list) or not route:
            return None
        out: List[Dict[str, Any]] = []
        for row in route:
            if not isinstance(row, list) or len(row) < 3:
                return None
            ts_ms, lat, lon = row[0], row[1], row[2]
            item = {"lat": float(lat), "lon": float(lon)}
            try:
                item["time"] = int(round(float(ts_ms) / 1000.0))
            except Exception:
                pass
            out.append(item)
        return out
    except Exception:
        return None

def _from_array_of_arrays(data: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(data, list) and data and all(isinstance(x, (list, tuple)) for x in data):
        out: List[Dict[str, Any]] = []
        for row in data:
            if len(row) >= 3 and isinstance(row[1], (int, float)) and isinstance(row[2], (int, float)):
                ts, lat, lon = row[0], row[1], row[2]
                item = {"lat": float(lat), "lon": float(lon)}
                try:
                    item["time"] = int(round(float(ts)))
                except Exception:
                    pass
            elif len(row) >= 2 and isinstance(row[0], (int, float)) and isinstance(row[1], (int, float)):
                item = {"lat": float(row[0]), "lon": float(row[1])}
            else:
                return None
            out.append(item)
        return out
    return None

def _from_geojson_featurecollection(data: Any) -> Optional[List[Dict[str, Any]]]:
    try:
        if isinstance(data, dict) and data.get("type") == "FeatureCollection":
            features = data.get("features")
            if not isinstance(features, list):
                return None
            coords: List[Tuple[float, float]] = []
            for feat in features:
                geom = (feat or {}).get("geometry") or {}
                gtype = geom.get("type")
                gcoords = geom.get("coordinates")
                if gtype == "LineString" and isinstance(gcoords, list):
                    coords = gcoords
                    break
            if not coords:
                for feat in features:
                    geom = (feat or {}).get("geometry") or {}
                    if geom.get("type") == "MultiLineString":
                        for line in geom.get("coordinates", []):
                            if isinstance(line, list):
                                coords.extend(line)
                        if coords:
                            break
            if coords:
                out: List[Dict[str, Any]] = []
                for c in coords:
                    if isinstance(c, (list, tuple)) and len(c) >= 2:
                        lon, lat = c[0], c[1]
                        out.append({"lat": float(lat), "lon": float(lon)})
                return out if out else None
    except Exception:
        return None
    return None

def normalize_points(data: Any) -> List[Dict[str, Any]]:
    for loader in (_from_array_of_dicts, _from_erictech_schema, _from_array_of_arrays, _from_geojson_featurecollection):
        res = loader(data)
        if res:
            return res
    raise ValueError("Formato não reconhecido para Valhalla.")

def _sample_vias(points: List[Dict[str, Any]], max_vias: int) -> List[Dict[str, Any]]:
    n = len(points)
    if n <= 2 or max_vias <= 0:
        return []
    mids = list(range(1, n - 1))
    if len(mids) <= max_vias:
        pick = mids
    else:
        step = len(mids) / float(max_vias + 1)
        pick = [mids[int(round(step * (i + 0.5)))] for i in range(max_vias)]
        pick = sorted(set(pick))
    return [points[i] for i in pick]

def _interp_timestamps_ms(points_in: List[Dict[str, Any]], count_out: int) -> List[int]:
    times_sec = [p.get("time") for p in points_in if isinstance(p.get("time"), (int, float))]
    if not times_sec:
        return [0 for _ in range(count_out)]
    t0_ms = int(min(times_sec) * 1000)
    t1_ms = int(max(times_sec) * 1000)
    if count_out <= 1:
        return [t0_ms]
    span = max(0, t1_ms - t0_ms)
    return [t0_ms + (span * i) // (count_out - 1) for i in range(count_out)]

def run():
    headless = len(sys.argv) >= 2
    if headless:
        src = Path(sys.argv[1]).expanduser().resolve()
        if not src.exists():
            print(f"Erro: arquivo não encontrado: {src}")
            return
    else:
        root = tk.Tk()
        root.withdraw()
        root.update()
        file_path = filedialog.askopenfilename(
            title="Selecione um arquivo JSON/GeoJSON de pontos",
            filetypes=[("JSON/GeoJSON", "*.json *.geojson"), ("Todos", "*.*")]
        )
        if not file_path:
            print("Operação cancelada pelo usuário.")
            return
        src = Path(file_path)

    try:
        with open(src, "r", encoding="utf-8") as f:
            raw = json.load(f)
        points_in = normalize_points(raw)
    except Exception as e:
        if headless:
            print(f"Erro no JSON: {e}")
        else:
            messagebox.showerror("Erro no JSON", f"O arquivo não pôde ser lido/validado:\n{e}")
        return

    if len(points_in) < 2:
        if headless:
            print("Poucos pontos: é necessário ao menos início e fim.")
        else:
            messagebox.showerror("Poucos pontos", "É necessário ao menos ponto inicial e final.")
        return

    start = points_in[0]
    end = points_in[-1]
    vias_raw = _sample_vias(points_in, MAX_VIAS)
    vias: List[Dict[str, Any]] = []
    for v in vias_raw:
        if is_point_on_valid_road(v["lat"], v["lon"]):
            vias.append(v)
    def _loc(p: Dict[str, Any], loc_type: str) -> Dict[str, Any]:
        return {
            "lon": p["lon"],
            "lat": p["lat"],
            "type": loc_type,
            "radius": LOCATE_MAX_DIST_M,
            "search_filter": {
                "min_road_class": "residential",
                "max_road_class": "motorway"
            }
        }
    locations = [_loc(start, "break")] + [
        _loc(v, "through") for v in vias
    ] + [_loc(end, "break")]

    payload = {
        "locations": locations,
        "costing": "auto",
        "directions_options": {"units": "kilometers"},
        "alternates": 0,
        "filters": {"attributes": ["shape"]}
    }

    try:
        resp = requests.post(VALHALLA_ROUTE, json=payload, timeout=90)
    except Exception as e:
        (print if headless else messagebox.showerror)("Erro de conexão", f"Falha ao chamar Valhalla /route:\n{e}")
        return

    if resp.status_code != 200:
        txt = resp.text
        if len(txt) > 700: txt = txt[:700] + "..."
        (print if headless else messagebox.showerror)("Erro do Valhalla", f"/route -> Status {resp.status_code}\n{txt}")
        return

    try:
        data = resp.json()
    except Exception:
        (print if headless else messagebox.showerror)("Erro", "Resposta do Valhalla /route não é JSON válido.")
        return

    trip = data.get("trip", {})
    poly_segments: List[str] = []
    if "legs" in trip:
        for leg in trip.get("legs", []):
            if "shape" in leg and leg["shape"]:
                poly_segments.append(leg["shape"])
    if not poly_segments and "shape" in trip and trip["shape"]:
        poly_segments.append(trip["shape"])
    if not poly_segments:
        (print if headless else messagebox.showerror)("Sem geometria", "Não encontrei 'shape' no retorno do /route.")
        return

    coords_latlon: List[Tuple[float, float]] = []
    for i, seg in enumerate(poly_segments):
        dec = decode_polyline6(seg)
        if i > 0 and coords_latlon and dec and coords_latlon[-1] == dec[0]:
            dec = dec[1:]
        coords_latlon.extend(dec)

    ts_ms_list = _interp_timestamps_ms(points_in, len(coords_latlon))
    osrm_route_rows = [[int(ts_ms), float(lat), float(lon)] for (lat, lon), ts_ms in zip(coords_latlon, ts_ms_list)]
    osrm_compat_obj = {"track": {"route": osrm_route_rows}}

    linestring_coords = [[float(lon), float(lat)] for (lat, lon) in coords_latlon]
    geojson_obj = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"source": "valhalla", "waypoint_count": len(locations)},
             "geometry": {"type": "LineString", "coordinates": linestring_coords}}
        ]
    }

    outdir = src.parent
    base = src.stem
    osrm_compat_path = outdir / f"{base}_matched_osrm_compat.json"
    geojson_path = outdir / f"{base}_route.geojson"

    try:
        with open(osrm_compat_path, "w", encoding="utf-8") as f:
            json.dump(osrm_compat_obj, f, ensure_ascii=False, indent=2)
        with open(geojson_path, "w", encoding="utf-8") as f:
            json.dump(geojson_obj, f, ensure_ascii=False, indent=2)
    except Exception as e:
        (print if headless else messagebox.showerror)("Erro ao salvar", f"Falha ao salvar saídas:\n{e}")
        return

    print("Saídas geradas em:")
    print(f" - {osrm_compat_path}")
    print(f" - {geojson_path}")

if __name__ == "__main__":
    run()