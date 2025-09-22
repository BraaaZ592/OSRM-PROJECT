
import json
import sys
import math
import requests
from pathlib import Path
from urllib.parse import quote
from typing import List, Tuple, Dict, Any, Optional
import hashlib

OSRM_HOST_DEFAULT = "http://127.0.0.1:5001"
VALHALLA_HOST_DEFAULT = "http://127.0.0.1:8002"

DP_TOL_DEFAULT    = 0.00008
DEDUP_EPS_M       = 3.0
OVERVIEW_MODE     = "full"
GAPS_MODE         = "ignore"

SAIDA_PASTA       = (Path.home() / "Desktop" / "OSRM Json")
SAIDA_ARQUIVO     = SAIDA_PASTA / "rota_unificada_corrigido.json"
SAIDA_GEOJSON_PASTA = Path(r"C:\\Users\\gabri\\Documents\\GEOJSON")
SAIDA_GEOJSON_ARQUIVO = SAIDA_GEOJSON_PASTA / "rota_unificada.geojson"

MIN_DIST_GAP   = 120.0
MAX_DT_GAP     = 15.0
MAX_VEL_GAP    = 33.0
GAP_HYST       = 2
RADIUS_SMALL    = 12
RADIUS_LARGE    = 18

SMOOTH_ENABLE: bool = True
SMOOTH_CHAIKIN_ITERS: int = 1
DENSIFY_ENABLE: bool = True
DENSIFY_STEP_M: float = 5.0
MAX_DEVIATION_M: float = 10.0

FENCE_POLYGON_DEFAULT: Optional[list[list[float]]] = [
    [-46.837352, -23.507503],
    [-46.837352, -23.507306],
    [-46.836199, -23.507306],
    [-46.836199, -23.507503],
    [-46.837352, -23.507503],
]
CACHE_DIR = Path.home() / ".cache" / "erictech_routing"
try:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

def _cache_get_json(key: str) -> Any:
    path = CACHE_DIR / f"{key}.json"
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None

def _cache_set_json(key: str, value: Any) -> None:
    path = CACHE_DIR / f"{key}.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False)
    except Exception:
        pass

def distancia_m(lon1, lat1, lon2, lat2):
    mean_lat = math.radians((lat1 + lat2) / 2.0)
    mx = (lon2 - lon1) * 111000.0 * math.cos(mean_lat)
    my = (lat2 - lat1) * 111000.0
    return math.hypot(mx, my)

def bearing(a: Tuple[float,float,int], b: Tuple[float,float,int]) -> int:
    lon1, lat1 = a[0], a[1]
    lon2, lat2 = b[0], b[1]
    lat1r = math.radians(lat1); lat2r = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(lat2r)
    x = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    brg = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return int(round(brg))

def _perp_dist_deg(pt_xy, a_xy, b_xy):
    if a_xy == b_xy:
        return math.hypot(pt_xy[0]-a_xy[0], pt_xy[1]-a_xy[1])
    num = abs((b_xy[0]-a_xy[0])*(a_xy[1]-pt_xy[1]) - (a_xy[0]-pt_xy[0])*(b_xy[1]-a_xy[1]))
    den = math.hypot(b_xy[0]-a_xy[0], b_xy[1]-a_xy[1])
    return num/den

def douglas_peucker(points: List[Tuple[float,float,int]], tol_deg: float) -> List[Tuple[float,float,int]]:
    if len(points) <= 2:
        return points[:]
    start, end = points[0], points[-1]
    index, maxd = 0, 0.0
    for i in range(1, len(points)-1):
        d = _perp_dist_deg((points[i][0], points[i][1]), (start[0], start[1]), (end[0], end[1]))
        if d > maxd:
            index, maxd = i, d
    if maxd > tol_deg:
        left  = douglas_peucker(points[:index+1], tol_deg)
        right = douglas_peucker(points[index:], tol_deg)
        return left[:-1] + right
    else:
        return [start, end]

def extrair_pontos(data) -> List[Tuple[float,float,int]]:
    pts: List[Tuple[float,float,int]] = []

    try:
        rota = data.get("track", {}).get("route", [])
        if isinstance(rota, list) and rota:
            for p in rota:
                if isinstance(p, (list, tuple)) and len(p) >= 3:
                    ts = int(round(float(p[0])))
                    if ts > 1e12:
                        ts = int(ts/1000)
                    lat_val = float(p[1]); lon_val = float(p[2])
                    if abs(lat_val) > 90 and abs(lon_val) <= 90:
                        lat_val, lon_val = lon_val, lat_val
                    pts.append((lon_val, lat_val, int(ts)))
            if pts:
                return pts
    except Exception:
        pass

    try:
        if data.get("type") == "FeatureCollection" and isinstance(data.get("features"), list):
            for feat in data["features"]:
                geom = (feat or {}).get("geometry") or {}
                if geom.get("type") == "LineString" and isinstance(geom.get("coordinates"), list):
                    ts = 0
                    out = []
                    for c in geom["coordinates"]:
                        if isinstance(c, (list, tuple)) and len(c) >= 2:
                            lon_val = float(c[0]); lat_val = float(c[1])
                            out.append((lon_val, lat_val, ts))
                            ts += 1
                    if out:
                        return out
            for feat in data["features"]:
                geom = (feat or {}).get("geometry") or {}
                if geom.get("type") == "MultiLineString":
                    ts = 0
                    out = []
                    for line in geom.get("coordinates", []):
                        for c in line:
                            if isinstance(c, (list, tuple)) and len(c) >= 2:
                                lon_val = float(c[0]); lat_val = float(c[1])
                                out.append((lon_val, lat_val, ts))
                                ts += 1
                    if out:
                        return out
    except Exception:
        pass

    if isinstance(data, list) and data:
        try:
            out = []
            ts_counter = 0
            for row in data:
                if isinstance(row, (list, tuple)):
                    if len(row) >= 3 and isinstance(row[1], (int, float)) and isinstance(row[2], (int, float)):
                        ts = int(round(float(row[0])))
                        if ts > 1e12:
                            ts = int(ts/1000)
                        lat_val = float(row[1]); lon_val = float(row[2])
                        out.append((lon_val, lat_val, ts))
                    elif len(row) >= 2 and isinstance(row[0], (int, float)) and isinstance(row[1], (int, float)):
                        lat_val = float(row[0]); lon_val = float(row[1])
                        out.append((lon_val, lat_val, ts_counter))
                        ts_counter += 1
            if out:
                return out
        except Exception:
            pass

    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
        out = []
        ts_counter = 0
        for p in data:
            if "lat" in p and "lon" in p:
                lat_val = float(p["lat"]); lon_val = float(p["lon"])
                if "time" in p:
                    try:
                        ts = int(round(float(p["time"])))
                        if ts > 1e12:
                            ts = int(ts/1000)
                    except Exception:
                        ts = ts_counter
                else:
                    ts = ts_counter
                out.append((lon_val, lat_val, ts))
                ts_counter = max(ts_counter+1, ts+1)
        if out:
            return out

    return []

def ordenar_por_ts(pontos: List[Tuple[float,float,int]]) -> List[Tuple[float,float,int]]:
    pts = sorted(pontos, key=lambda x: x[2])
    out, last = [], None
    for lon, lat, ts in pts:
        if last is not None and ts <= last:
            ts = last + 1
        out.append((lon, lat, ts))
        last = ts
    return out

def dedupe_por_raio(pontos: List[Tuple[float,float,int]], eps_m: float) -> List[Tuple[float,float,int]]:
    if not pontos: return []
    kept = [pontos[0]]
    for p in pontos[1:]:
        if distancia_m(kept[-1][0], kept[-1][1], p[0], p[1]) >= eps_m:
            kept.append(p)
        else:
            if p[2] > kept[-1][2]:
                kept[-1] = p
    return kept

def montar_url_match(pts: List[Tuple[float,float,int]], host: str, overview: str, gaps: str) -> str:
    coords = ";".join(f"{lon},{lat}" for lon, lat, _ in pts)
    timestamps = ";".join(str(ts) for _, _, ts in pts)
    radiuses_list: List[str] = []
    for i, (lon, lat, _) in enumerate(pts):
        if i == 0 or i == len(pts)-1:
            r = RADIUS_LARGE
        else:
            d_prev = distancia_m(pts[i-1][0], pts[i-1][1], lon, lat)
            d_next = distancia_m(lon, lat, pts[i+1][0], pts[i+1][1])
            r = RADIUS_SMALL if max(d_prev, d_next) < 30.0 else RADIUS_LARGE
        radiuses_list.append(str(int(r)))
    radiuses = ";".join(radiuses_list)
    bearings_vals: List[str] = []
    for i in range(len(pts)):
        if i == 0 or i == len(pts)-1:
            bearings_vals.append("")
        else:
            b = bearing(pts[i-1], pts[i+1])
            bearings_vals.append(f"{b},90")
    bearings = ";".join(bearings_vals)

    qs = (
        f"geometries=geojson"
        f"&overview={overview}"
        f"&gaps={gaps}"
        f"&timestamps={timestamps}"
        f"&radiuses={radiuses}"
        f"&bearings={bearings}"
        f"&tidy=true"
    )
    return f"{host}/match/v1/driving/{quote(coords, safe=';,')}?{qs}"

def call_route(start_coord: Tuple[float,float], end_coord: Tuple[float,float], host: str) -> List[List[float]]:
    coords_str = f"{start_coord[0]},{start_coord[1]};{end_coord[0]},{end_coord[1]}"
    url_route = f"{host}/route/v1/driving/{coords_str}?geometries=geojson&overview=full&continue_straight=true"
    cache_key = "osrm_route_" + hashlib.md5(url_route.encode()).hexdigest()
    cached = _cache_get_json(cache_key)
    if cached:
        try:
            routes = cached.get("routes") or []
            if routes and routes[0].get("geometry", {}).get("coordinates"):
                return routes[0]["geometry"]["coordinates"]
        except Exception:
            pass
    try:
        r = requests.get(url_route, timeout=30)
        r.raise_for_status()
        rj = r.json()
        _cache_set_json(cache_key, rj)
        if rj.get("routes") and rj["routes"][0]["geometry"]["coordinates"]:
            return rj["routes"][0]["geometry"]["coordinates"]
    except Exception as e:
        print(f"Falha ao chamar /route: {e}")
    return []

def call_route_multi(points: List[Tuple[float,float]], host: str) -> List[List[float]]:
    if not points or len(points) < 2:
        return []
    coords_str = ";".join(f"{lon},{lat}" for lon, lat in points)
    url = f"{host}/route/v1/driving/{coords_str}?geometries=geojson&overview=full&continue_straight=true"
    cache_key = "osrm_route_multi_" + hashlib.md5(url.encode()).hexdigest()
    cached = _cache_get_json(cache_key)
    if cached:
        try:
            routes = cached.get("routes") or []
            if routes and routes[0].get("geometry", {}).get("coordinates"):
                return routes[0]["geometry"]["coordinates"]
        except Exception:
            pass
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        rj = r.json()
        _cache_set_json(cache_key, rj)
        if rj.get("routes") and rj["routes"][0]["geometry"]["coordinates"]:
            return rj["routes"][0]["geometry"]["coordinates"]
    except Exception as e:
        print(f"Falha ao chamar /route multi: {e}")
    return []

def _valhalla_post_json(url: str, payload: dict) -> Optional[dict]:
    try:
        r = requests.post(url, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Falha Valhalla: {e}")
        return None

def call_valhalla_trace_route(points: List[Tuple[float,float,int]], host: str) -> List[List[float]]:
    if not points or len(points) < 2:
        return []
    shape = []
    for lon, lat, ts in points:
        shape.append({"lat": lat, "lon": lon, "time": int(ts) if ts is not None else 0})
    payload = {
        "shape": shape,
        "costing": "auto",
        "shape_match": "map_snap",
        "use_timestamps": True,
        "format": "geojson"
    }
    url = f"{host.rstrip('/')}/trace_route"
    data = _valhalla_post_json(url, payload)
    if not data:
        return []
    try:
        coords: List[List[float]] = []
        feats = data.get("features") or []
        for feat in feats:
            geom = (feat or {}).get("geometry") or {}
            if geom.get("type") == "LineString":
                for c in geom.get("coordinates") or []:
                    coords.append([float(c[0]), float(c[1])])
        return coords
    except Exception:
        return []

def _parse_fence_poly(s: str) -> Optional[list[list[float]]]:
    try:
        pts = []
        for pair in s.strip().split(";"):
            if not pair.strip():
                continue
            lon_str, lat_str = pair.split(",", 1)
            pts.append([float(lon_str), float(lat_str)])
        return pts if len(pts) >= 3 else None
    except Exception:
        return None

def point_in_poly(lon: float, lat: float, poly: list[list[float]]) -> bool:
    inside = False
    n = len(poly)
    if n < 3:
        return False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cond = ((y1 > lat) != (y2 > lat))
        if cond:
            x_intersect = (x2 - x1) * (lat - y1) / (y2 - y1 + 1e-15) + x1
            if lon < x_intersect:
                inside = not inside
    return inside

def split_by_fence(pontos_ordenados: List[Tuple[float,float,int]],
                   fence_poly: Optional[list[list[float]]]) -> List[Tuple[str, List[Tuple[float,float,int]]]]:
    if not pontos_ordenados or len(pontos_ordenados) < 2:
        return []
    if not fence_poly:
        return [("osrm", pontos_ordenados[:])]

    def engine_for(lon, lat) -> str:
        return "valhalla" if point_in_poly(lon, lat, fence_poly) else "osrm"

    out = []
    cur_engine = engine_for(pontos_ordenados[0][0], pontos_ordenados[0][1])
    cur_seg = [pontos_ordenados[0]]

    for p in pontos_ordenados[1:]:
        eng = engine_for(p[0], p[1])
        if eng == cur_engine:
            cur_seg.append(p)
        else:
            if len(cur_seg) >= 2:
                out.append((cur_engine, cur_seg))
            cur_engine = eng
            cur_seg = [cur_seg[-1], p] 
    if len(cur_seg) >= 2:
        out.append((cur_engine, cur_seg))
    return out

def _process_segment_by_engine(segmento: List[Tuple[float,float,int]],
                               engine: str,
                               osrm_host: str,
                               valhalla_host: str,
                               overview: str,
                               gaps: str) -> List[List[float]]:
    if engine == "valhalla":
        coords = call_valhalla_trace_route(segmento, valhalla_host)
        if coords:
            return coords
    if len(segmento) > 1:
        try:
            url_match = montar_url_match(segmento, osrm_host, overview, gaps)
            resp = requests.get(url_match, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            matchings = data.get("matchings") or []
            if matchings:
                out = []
                for m in matchings:
                    geom = m.get("geometry") or {}
                    if geom.get("type") == "LineString" and geom.get("coordinates"):
                        out.extend([[c[0], c[1]] for c in geom["coordinates"]])
                if out:
                    return out
        except Exception as e:
            print(f"Falha /match OSRM: {e}")
    return []

def _smooth_and_densify(path: List[List[float]]) -> List[List[float]]:
    if not path:
        return path

    def _distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        mean_lat = math.radians((lat1 + lat2) / 2.0)
        mx = (lon2 - lon1) * 111000.0 * math.cos(mean_lat)
        my = (lat2 - lat1) * 111000.0
        return math.hypot(mx, my)

    def _chaikin_once_path(path: List[List[float]], keep_idx: set) -> List[List[float]]:
        if not path:
            return path
        out: List[List[float]] = [path[0]]
        for i in range(1, len(path) - 1):
            if i in keep_idx:
                out.append(path[i])
                continue
            lon0, lat0 = path[i]
            lon1, lat1 = path[i + 1]
            q = [0.75 * lon0 + 0.25 * lon1, 0.75 * lat0 + 0.25 * lat1]
            r = [0.25 * lon0 + 0.75 * lon1, 0.25 * lat0 + 0.75 * lat1]
            out.append(q)
            out.append(r)
        out.append(path[-1])
        return out

    def _densify_path(path: List[List[float]], step_m: float = 5.0) -> List[List[float]]:
        if not path:
            return path
        out: List[List[float]] = [path[0]]
        for a, b in zip(path, path[1: ]):
            dist = _distance_m(a[0], a[1], b[0], b[1])
            if dist <= 0.0 or dist <= step_m:
                out.append(b)
                continue
            n = int(dist // step_m)
            for k in range(1, n + 1):
                t = min(1.0, (k * step_m) / dist)
                lon = a[0] + t * (b[0] - a[0])
                lat = a[1] + t * (b[1] - a[1])
                out.append([lon, lat])
            out.append(b)
        return out

    def _compute_keep_indices(path: List[List[float]]) -> set:
        keep = set()
        if not path:
            return keep
        keep.add(0)
        keep.add(len(path) - 1)
        for i in range(1, len(path) - 1):
            dx0 = path[i][0] - path[i - 1][0]
            dy0 = path[i][1] - path[i - 1][1]
            dx1 = path[i + 1][0] - path[i][0]
            dy1 = path[i + 1][1] - path[i][1]
            ang0 = math.degrees(math.atan2(dy0, dx0))
            ang1 = math.degrees(math.atan2(dy1, dx1))
            diff = abs(ang1 - ang0)
            if diff > 180:
                diff = 360 - diff
            if diff >= 35.0:
                keep.add(i)
        return keep

    keep_idx = _compute_keep_indices(path)
    new_path = [p[:] for p in path]
    if SMOOTH_ENABLE:
        for _ in range(max(0, SMOOTH_CHAIKIN_ITERS)):
            new_path = _chaikin_once_path(new_path, keep_idx)
    if DENSIFY_ENABLE:
        new_path = _densify_path(new_path, step_m=DENSIFY_STEP_M)
    return new_path

def processar_uma_trilha(
    pontos_brutos: List[Tuple[float, float, int]],
    host: str = OSRM_HOST_DEFAULT,
    dp_tol: float = DP_TOL_DEFAULT,
    eps_m: float = DEDUP_EPS_M,
    overview: str = OVERVIEW_MODE,
    gaps: str = GAPS_MODE,
    valhalla_host: str = VALHALLA_HOST_DEFAULT,
    fence_poly: Optional[list[list[float]]] = None,
) -> Tuple[Dict[str, Any], str, bool]:
    if not pontos_brutos or len(pontos_brutos) < 2:
        return None, "Nenhum ponto valido para processar.", False

    ordenados = ordenar_por_ts(pontos_brutos)
    dedup = dedupe_por_raio(ordenados, eps_m)
    engine_segments = split_by_fence(dedup, fence_poly)

    final_path: List[List[float]] = []

    for engine, seg in engine_segments:
        if len(seg) >= 10:
            seg_proc = douglas_peucker(seg, dp_tol)
        else:
            seg_proc = seg[:]

        coords = _process_segment_by_engine(seg_proc, engine, host, valhalla_host, overview, gaps)

        if not coords and len(seg_proc) >= 2:
            lon0, lat0, _ = seg_proc[0]
            lon1, lat1, _ = seg_proc[-1]
            bridge = call_route((lon0, lat0), (lon1, lat1), host)
            if bridge:
                coords = bridge
            else:
                coords = [[lon, lat] for lon, lat, _ in seg_proc]
        for c in coords:
            if final_path and final_path[-1] == c:
                continue
            final_path.append(c)

    if not final_path:
        return None, "Nenhuma rota valida encontrada.", False
    try:
        last_raw = ordenados[-1]
        last_coord = final_path[-1]
        if last_coord != [last_raw[0], last_raw[1]]:
            d_tail = distancia_m(last_coord[0], last_coord[1], last_raw[0], last_raw[1])
            if d_tail > 30.0:
                bridging_route = call_route((last_coord[0], last_coord[1]),
                                            (last_raw[0],  last_raw[1]), host)
                if bridging_route:
                    dist_route = 0.0
                    for a, b in zip(bridging_route, bridging_route[1:]):
                        dist_route += distancia_m(a[0], a[1], b[0], b[1])
                    if d_tail > 0 and dist_route <= (3.0 * d_tail + 50.0):
                        start_idx = 1 if bridging_route[0] == last_coord else 0
                        for coord in bridging_route[start_idx:]:
                            if not final_path or final_path[-1] != coord:
                                final_path.append(coord)
        if final_path[-1] != [last_raw[0], last_raw[1]]:
            d_tail2 = distancia_m(final_path[-1][0], final_path[-1][1], last_raw[0], last_raw[1])
            if 2.0 < d_tail2 <= 30.0:
                final_path.append([last_raw[0], last_raw[1]])
    except Exception as e:
        print(f"Falha ao costurar chegada: {e}")
        if final_path and final_path[-1] != [ordenados[-1][0], ordenados[-1][1]]:
            final_path.append([ordenados[-1][0], ordenados[-1][1]])
    if (SMOOTH_ENABLE or DENSIFY_ENABLE) and final_path:
        try:
            final_path = _smooth_and_densify(final_path)
        except Exception as e:
            print(f"Aviso: pós‑processamento falhou: {e}")

    features = []
    linha_unica = {"type": "LineString", "coordinates": final_path}
    features.append({"type": "Feature", "properties": {"stitched": True}, "geometry": linha_unica})
    features.append({"type": "Feature", "properties": {"final_point": True}, "geometry": {"type": "Point", "coordinates": [ordenados[-1][0], ordenados[-1][1]]}})

    geojson_final = {"type": "FeatureCollection", "features": features}
    return geojson_final, "Sucesso no processamento.", True

def parse_args(argv: List[str]) -> Dict[str, Any]:
    args: Dict[str, Any] = {
        "files": [],
        "host": OSRM_HOST_DEFAULT,
        "valhalla_host": VALHALLA_HOST_DEFAULT,
        "fence": None,
        "dp": DP_TOL_DEFAULT,
        "eps": DEDUP_EPS_M,
        "overview": OVERVIEW_MODE,
        "gaps": GAPS_MODE,
    }
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("--host="):
            args["host"] = arg.split("=", 1)[1]
        elif arg.startswith("--valhalla_host="):
            args["valhalla_host"] = arg.split("=", 1)[1]
        elif arg.startswith("--fence="):
            args["fence"] = arg.split("=", 1)[1]
        elif arg.startswith("--dp="):
            args["dp"] = float(arg.split("=", 1)[1])
        elif arg.startswith("--eps="):
            args["eps"] = float(arg.split("=", 1)[1])
        elif arg.startswith("--overview="):
            args["overview"] = arg.split("=", 1)[1]
        elif arg.startswith("--gaps="):
            args["gaps"] = arg.split("=", 1)[1]
        elif arg in ("--host", "--valhalla_host", "--fence", "--dp", "--eps", "--overview", "--gaps"):
            i += 1
            if i >= len(argv):
                raise SystemExit(f"Parametro {arg} requer valor.")
            val = argv[i]
            if arg == "--host":
                args["host"] = val
            elif arg == "--valhalla_host":
                args["valhalla_host"] = val
            elif arg == "--fence":
                args["fence"] = val
            elif arg == "--dp":
                args["dp"] = float(val)
            elif arg == "--eps":
                args["eps"] = float(val)
            elif arg == "--overview":
                args["overview"] = val
            elif arg == "--gaps":
                args["gaps"] = val
        else:
            args["files"].append(arg)
        i += 1
    return args

def escolher_arquivos():
    try:
        from tkinter import Tk, filedialog
        Tk().withdraw()
        sel = filedialog.askopenfilenames(
            title="Selecione 1+ arquivos JSON de rota",
            filetypes=[("Arquivos JSON", "*.json")]
        )
        return list(sel)
    except Exception:
        return []

def main():
    argv = sys.argv[1:]
    args = parse_args(argv)

    files = args["files"]
    if not files:
        files = escolher_arquivos()
    if len(files) < 1:
        print("Selecione pelo menos 1 arquivo de rota (JSON).")
        sys.exit(1)

    brutos = []
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            pts = extrair_pontos(data)
            if not pts:
                print(f"{path}: sem pontos validos.")
                continue
            brutos.extend(pts)
        except Exception as e:
            print(f"Erro em {path}: {e}")

    if not brutos:
        print("Nenhum ponto nos arquivos informados.")
        sys.exit(1)

    fence_poly = None
    if args.get("fence"):
        fence_poly = _parse_fence_poly(args["fence"])
    if not fence_poly and FENCE_POLYGON_DEFAULT:
        fence_poly = FENCE_POLYGON_DEFAULT

    geojson_data, msg, ok = processar_uma_trilha(
        pontos_brutos=brutos,
        host=args["host"],
        dp_tol=args["dp"],
        eps_m=args["eps"],
        overview=args["overview"],
        gaps=args["gaps"],
        valhalla_host=args.get("valhalla_host", VALHALLA_HOST_DEFAULT),
        fence_poly=fence_poly,
    )

    if ok:
        SAIDA_PASTA.mkdir(parents=True, exist_ok=True)
        with open(SAIDA_ARQUIVO, "w", encoding="utf-8") as f:
            json.dump(geojson_data, f, ensure_ascii=False, indent=2)
        try:
            SAIDA_GEOJSON_PASTA.mkdir(parents=True, exist_ok=True)
            with open(SAIDA_GEOJSON_ARQUIVO, "w", encoding="utf-8") as f_out:
                json.dump(geojson_data, f_out, ensure_ascii=False, indent=2)
            print(f"GeoJSON salvo em: {SAIDA_ARQUIVO} e {SAIDA_GEOJSON_ARQUIVO}")
        except Exception as e:
            print(f"GeoJSON salvo em: {SAIDA_ARQUIVO}. Falha ao salvar em {SAIDA_GEOJSON_ARQUIVO}: {e}")
    else:
        print(f"Falha no processamento: {msg}")

if __name__ == "__main__":
    main()
