import json
import sys
import math
import requests
from pathlib import Path
from urllib.parse import quote
from typing import List, Tuple, Dict, Any

OSRM_HOST_DEFAULT = "http://127.0.0.1:5001"

DP_TOL_DEFAULT    = 0.00008
DEDUP_EPS_M       = 3.0
OVERVIEW_MODE     = "full"
GAPS_MODE         = "ignore"
SAIDA_PASTA       = Path.home() / "Documents" / "geojson"
SAIDA_ARQUIVO     = SAIDA_PASTA / "rota_unificada.geojson"

MIN_DIST_GAP   = 120.0  
MAX_DT_GAP     = 15.0    
MAX_VEL_GAP    = 33.0    
GAP_HYST       = 2
RADIUS_SMALL    = 30
RADIUS_LARGE    = 50

def parse_args(argv: List[str]) -> Dict[str, Any]:
    """
    Parse command line arguments and return a dictionary of values.

    Supported options:

    --host=<url>        URL of the OSRM server (default: OSRM_HOST_DEFAULT)
    --dp=<value>        Douglas–Peucker tolerance (degrees)
    --eps=<value>       Deduplication radius (metres)
    --overview=<mode>   OSRM overview mode
    --gaps=<mode>       OSRM gaps policy

    Positional arguments that do not start with '--' are treated as file
    paths for JSON tracks.  Valhalla support has been removed, so
    options prefixed with --valhalla_host are ignored.
    """
    args: Dict[str, Any] = {
        "files": [],
        "host": OSRM_HOST_DEFAULT,
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
        elif arg.startswith("--dp="):
            args["dp"] = float(arg.split("=", 1)[1])
        elif arg.startswith("--eps="):
            args["eps"] = float(arg.split("=", 1)[1])
        elif arg.startswith("--overview="):
            args["overview"] = arg.split("=", 1)[1]
        elif arg.startswith("--gaps="):
            args["gaps"] = arg.split("=", 1)[1]
        elif arg in ("--host", "--dp", "--eps", "--overview", "--gaps"):
            i += 1
            if i >= len(argv):
                raise SystemExit(f"Parametro {arg} requer valor.")
            val = argv[i]
            if arg == "--host":
                args["host"] = val
            elif arg == "--dp":
                args["dp"] = float(val)
            elif arg == "--eps":
                args["eps"] = float(val)
            elif arg == "--overview":
                args["overview"] = val
            elif arg == "--gaps":
                args["gaps"] = val
        elif arg.startswith("--valhalla_host"):
            if "=" not in arg:
                i += 1 
        else:
            args["files"].append(arg)
        i += 1
    return args

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
    rota = data.get("track", {}).get("route", [])
    pts: List[Tuple[float,float,int]] = []
    for p in rota:
        if isinstance(p, (list, tuple)) and len(p) >= 3:
            ts = int(p[0] / 1000)
            lat_val = float(p[1])
            lon_val = float(p[2])
            if abs(lat_val) > 90 and abs(lon_val) <= 90:
                lat_val, lon_val = lon_val, lat_val
            pts.append((lon_val, lat_val, ts))
    return pts

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
    try:
        r = requests.get(url_route, timeout=30)
        r.raise_for_status()
        rj = r.json()
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
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        rj = r.json()
        if rj.get("routes") and rj["routes"][0]["geometry"]["coordinates"]:
            return rj["routes"][0]["geometry"]["coordinates"]
    except Exception as e:
        print(f"Falha ao chamar /route multi: {e}")
    return []


def processar_uma_trilha(
    pontos_brutos: List[Tuple[float, float, int]],
    host: str = OSRM_HOST_DEFAULT,
    dp_tol: float = DP_TOL_DEFAULT,
    eps_m: float = DEDUP_EPS_M,
    overview: str = OVERVIEW_MODE,
    gaps: str = GAPS_MODE
) -> Tuple[Dict[str, Any], str, bool]:
    if not pontos_brutos or len(pontos_brutos) < 2:
        return None, "Nenhum ponto valido para processar.", False

    ordenados = ordenar_por_ts(pontos_brutos)
    dedup = dedupe_por_raio(ordenados, eps_m)
    
    final_path: List[List[float]] = []
    
    gap_flags = 0
    current_segment = [dedup[0]]
    for i in range(1, len(dedup)):
        lon0, lat0, ts0 = dedup[i-1]
        lon1, lat1, ts1 = dedup[i]
        dist = distancia_m(lon0, lat0, lon1, lat1)
        dt   = max(0, ts1 - ts0)
        vel  = (dist / dt) if dt > 0 else float("inf")
        is_gap = (dt >= MAX_DT_GAP) or (dist >= MIN_DIST_GAP and vel >= MAX_VEL_GAP)
        if is_gap:
            gap_flags += 1
        else:
            gap_flags = 0
        if gap_flags >= GAP_HYST:
            if len(current_segment) < 10:
                simplificado_segmento = current_segment[:]
            else:
                simplificado_segmento = douglas_peucker(current_segment, dp_tol)

            match_sucesso = False
            if len(simplificado_segmento) > 1:
                url_match = montar_url_match(simplificado_segmento, host, overview, gaps)
                try:
                    resp = requests.get(url_match, timeout=60)
                    resp.raise_for_status()
                    data = resp.json()
                    matchings = data.get("matchings") or []
                    if matchings:
                        for m in matchings:
                            geom = m.get("geometry") or {}
                            if geom.get("type") == "LineString" and geom.get("coordinates"):
                                final_path.extend([[c[0], c[1]] for c in geom["coordinates"]])
                                match_sucesso = True
                except Exception as e:
                    print(f"Falha no /match para segmento. Erro: {e}")
                if not match_sucesso:
                    url_match2 = montar_url_match(simplificado_segmento, host, overview, "split")
                    try:
                        resp2 = requests.get(url_match2, timeout=60)
                        resp2.raise_for_status()
                        data2 = resp2.json()
                        matchings2 = data2.get("matchings") or []
                        if matchings2:
                            for m in matchings2:
                                geom = m.get("geometry") or {}
                                if geom.get("type") == "LineString" and geom.get("coordinates"):
                                    final_path.extend([[c[0], c[1]] for c in geom["coordinates"]])
                                    match_sucesso = True
                    except Exception as e:
                        print(f"Falha no /match (gaps=split) para segmento. Erro: {e}")

            if not match_sucesso:
                print(
                    f"Gap de {dist:.2f} m / {dt:.1f} s; match falhou. Tentando preencher somente entre pontos consecutivos com /route."
                )
                bridging_route: List[List[float]] = call_route((lon0, lat0), (lon1, lat1), host)
                use_raw_segment = False
                if bridging_route:
                    dist_route = 0.0
                    for a, b in zip(bridging_route, bridging_route[1:]):
                        dist_route += distancia_m(a[0], a[1], b[0], b[1])
                    direct_dist = dist
                    if direct_dist > 0 and dist_route / direct_dist > 5.0:
                        use_raw_segment = True
                else:
                    use_raw_segment = True

                if use_raw_segment:
                    for lon_raw, lat_raw, _ in simplificado_segmento:
                        if final_path and final_path[-1] == [lon_raw, lat_raw]:
                            continue
                        final_path.append([lon_raw, lat_raw])
                else:
                    if final_path and final_path[-1] == bridging_route[0]:
                        final_path.extend(bridging_route[1:])
                    else:
                        final_path.extend(bridging_route)
            current_segment = [dedup[i]]
            gap_flags = 0
        else:
            current_segment.append(dedup[i])

    if current_segment and len(current_segment) > 1:
        if len(current_segment) < 10:
            simplificado_segmento = current_segment[:]
        else:
            simplificado_segmento = douglas_peucker(current_segment, dp_tol)
        if len(simplificado_segmento) > 1:
            match_sucesso = False
            url_match = montar_url_match(simplificado_segmento, host, overview, gaps)
            try:
                resp = requests.get(url_match, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                matchings = data.get("matchings") or []
                if matchings:
                    for m in matchings:
                        geom = m.get("geometry") or {}
                        if geom.get("type") == "LineString" and geom.get("coordinates"):
                            final_path.extend([[c[0], c[1]] for c in geom["coordinates"]])
                            match_sucesso = True
            except Exception as e:
                print(f"Falha no /match para segmento final. Erro: {e}")
            if not match_sucesso:
                url_match2 = montar_url_match(simplificado_segmento, host, overview, "split")
                try:
                    resp2 = requests.get(url_match2, timeout=60)
                    resp2.raise_for_status()
                    data2 = resp2.json()
                    matchings2 = data2.get("matchings") or []
                    if matchings2:
                        for m in matchings2:
                            geom = m.get("geometry") or {}
                            if geom.get("type") == "LineString" and geom.get("coordinates"):
                                final_path.extend([[c[0], c[1]] for c in geom["coordinates"]])
                                match_sucesso = True
                except Exception as e:
                    print(f"Falha no /match (gaps=split) para segmento final. Erro: {e}")
            if not match_sucesso:
                lon0, lat0, _ = simplificado_segmento[0]
                lon1, lat1, _ = simplificado_segmento[-1]
                bridging_route: List[List[float]] = call_route((lon0, lat0), (lon1, lat1), host)
                use_raw_segment = False
                if bridging_route:
                    dist_route = 0.0
                    for a, b in zip(bridging_route, bridging_route[1:]):
                        dist_route += distancia_m(a[0], a[1], b[0], b[1])
                    direct_dist = distancia_m(lon0, lat0, lon1, lat1)
                    if direct_dist > 0 and dist_route / direct_dist > 5.0:
                        use_raw_segment = True
                else:
                    use_raw_segment = True

                if use_raw_segment:
                    for lon_raw, lat_raw, _ in simplificado_segmento:
                        if final_path and final_path[-1] == [lon_raw, lat_raw]:
                            continue
                        final_path.append([lon_raw, lat_raw])
                else:
                    if final_path and final_path[-1] == bridging_route[0]:
                        final_path.extend(bridging_route[1:])
                    else:
                        final_path.extend(bridging_route)

    dedup_path: List[List[float]] = []
    for coord in final_path:
        if not dedup_path or dedup_path[-1] != coord:
            dedup_path.append(coord)

    if not dedup_path:
        return None, "Nenhuma rota valida encontrada.", False

    try:
        last_raw = ordenados[-1]  # (lon, lat, ts)
        last_coord = dedup_path[-1]  # [lon, lat]

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
                            if not dedup_path or dedup_path[-1] != coord:
                                dedup_path.append(coord)
        if dedup_path[-1] != [last_raw[0], last_raw[1]]:
            d_tail2 = distancia_m(dedup_path[-1][0], dedup_path[-1][1], last_raw[0], last_raw[1])
            if 2.0 < d_tail2 <= 30.0:
                dedup_path.append([last_raw[0], last_raw[1]])
    except Exception as e:
        print(f"Falha ao costurar chegada: {e}")
        if dedup_path and dedup_path[-1] != [ordenados[-1][0], ordenados[-1][1]]:
            dedup_path.append([ordenados[-1][0], ordenados[-1][1]])

    features = []
    linha_unica = {"type": "LineString", "coordinates": dedup_path}
    features.append({"type": "Feature", "properties": {"stitched": True}, "geometry": linha_unica})
    features.append({"type": "Feature", "properties": {"final_point": True}, "geometry": {"type": "Point", "coordinates": [ordenados[-1][0], ordenados[-1][1]]}})

    geojson_final = {"type": "FeatureCollection", "features": features}
    return geojson_final, "Sucesso no processamento.", True

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

    geojson_data, msg, ok = processar_uma_trilha(
        pontos_brutos=brutos,
        host=args["host"],
        dp_tol=args["dp"],
        eps_m=args["eps"],
        overview=args["overview"],
        gaps=args["gaps"]
    )

    if ok:
        SAIDA_PASTA.mkdir(parents=True, exist_ok=True)
        with open(SAIDA_ARQUIVO, "w", encoding="utf-8") as f:
            json.dump(geojson_data, f, ensure_ascii=False, indent=2)
        print(f"GeoJSON salvo em: {SAIDA_ARQUIVO}")
    else:
        print(f"Falha no processamento: {msg}")

if __name__ == "__main__":
    main()