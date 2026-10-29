"""
Backend API cho web dự báo TVDI (FastAPI + PostgreSQL/PostGIS).

Chạy từ thư mục dự án (tvdi_web):
    uvicorn main:app --reload --port 8000
Mở: http://localhost:8000

Biến môi trường (.env):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tvdi_hcm
    ADMIN_TOKEN=matkhau_admin_cua_ban
"""
import json
import os
import re
import secrets
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

# Thư mục gốc dự án
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/tvdi_hcm"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DB_URL)
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")  # Rỗng = tắt admin

MODEL_PATH = ROOT / "model" / "tvdi_model.joblib"
MODEL_NAME = "GRU - TVDI"
N_LAGS = 6

app = FastAPI(title="TVDI - Dự báo khô hạn TP.HCM (FastAPI + PostgreSQL)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_pool: Optional[ThreadedConnectionPool] = None
_ward_geoms: dict = {}
_model_bundle = None

CLASSES = [
    (0, "Rất ẩm"),
    (1, "Ẩm"),
    (2, "Trung bình"),
    (3, "Khô"),
    (4, "Rất khô"),
]

# =====================================================================
# HELPER
# =====================================================================
def classify(val):
    if val is None:
        return 2
    v = float(val)
    if v < 0.2:
        return 0
    if v < 0.4:
        return 1
    if v < 0.6:
        return 2
    if v < 0.8:
        return 3
    return 4


def class_label(idx):
    return CLASSES[idx][1] if 0 <= idx < len(CLASSES) else "Không có dữ liệu"


def clean_ward_name(name: str) -> str:
    if not name:
        return ""
    s = str(name).strip().lower()
    s = re.sub(r"^(phường|xã|thị trấn|tt\.)\s+", "", s)
    return " ".join(s.split())


def add_months(year: int, month: int, delta: int):
    m = month - 1 + delta
    y = year + m // 12
    m = m % 12 + 1
    return y, m


def _metric_col(metric: str) -> str:
    mapping = {
        "tvdi": "tvdi_mean",
        "lst": "lst_mean",
        "ndvi": "ndvi_mean",
    }
    if metric not in mapping:
        raise HTTPException(400, f"Chỉ số không hỗ trợ: {metric}")
    return mapping[metric]


# =====================================================================
# ADMIN GATE
# =====================================================================
def require_admin(x_admin_token: str = Header(default="")):
    if not ADMIN_TOKEN:
        raise HTTPException(503, "Server chưa cấu hình ADMIN_TOKEN trong file .env.")
    if not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(403, "Chỉ admin mới được thực hiện thao tác này.")


# =====================================================================
# DB CONNECTION
# =====================================================================
def get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise HTTPException(503, "Chưa cấu hình DATABASE_URL trong file .env.")
        try:
            _pool = ThreadedConnectionPool(1, 10, DATABASE_URL)
        except Exception as e:
            raise HTTPException(503, f"Không kết nối được PostgreSQL: {e}")
    return _pool


@contextmanager
def cursor(commit: bool = False):
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def get_ward_geoms() -> dict:
    global _ward_geoms
    if not _ward_geoms:
        with cursor() as cur:
            cur.execute(
                """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'phuong_xa_full';
                """
            )
            cols = {r["column_name"].lower() for r in cur.fetchall()}

            name_parts = []
            for col in ["fullname", "name", "ward_name", "ten_phuong", "ten_xa", "f_name"]:
                if col in cols:
                    name_parts.append(f"NULLIF({col}::text, '')")
            name_parts.append("'Phường/Xã ' || gid")
            name_expr = f"COALESCE({', '.join(name_parts)})"

            query = f"""
                SELECT 
                    gid::text AS gid_code,
                    {name_expr} AS ward_name,
                    ROUND((ST_Area(ST_Transform(ST_SetSRID(geom, 4326), 3857)) / 1000000.0)::numeric, 2)::float AS area_km2,
                    ST_AsGeoJSON(ST_SimplifyPreserveTopology(ST_SetSRID(geom, 4326), 0.0003), 5) AS g
                FROM public.phuong_xa_full 
                ORDER BY gid
            """
            cur.execute(query)
            _ward_geoms = {}
            for r in cur.fetchall():
                w_name = str(r["ward_name"]).strip()
                gid_code = str(r["gid_code"]).strip()
                c_name = clean_ward_name(w_name)
                item = {
                    "gid": gid_code,
                    "name": w_name,
                    "clean_name": c_name,
                    "area_km2": r["area_km2"],
                    "geometry": json.loads(r["g"]),
                }
                _ward_geoms[gid_code] = item
                _ward_geoms[w_name] = item
                _ward_geoms[c_name] = item
    return _ward_geoms


def _fetch_metric_rows(nam: int, thang: int, loai: str) -> dict:
    with cursor() as cur:
        if loai == "du_bao" or nam >= 2026:
            query = """
                SELECT TRIM(ward_code::text) AS ward_code,
                       tvdi_du_bao::float AS tvdi
                FROM tvdi_forecast
                WHERE nam=%s AND thang=%s AND tvdi_du_bao IS NOT NULL;
            """
            cur.execute(query, (nam, thang))
            rows = cur.fetchall()
            return {
                str(r["ward_code"]).strip(): {
                    "tvdi_mean": r["tvdi"], "lst_mean": None, "ndvi_mean": None,
                }
                for r in rows
            }
        else:
            query = """
                SELECT TRIM(ward_code::text) AS ward_code,
                       tvdi_mean::float AS tvdi
                FROM tvdi_by_ward
                WHERE nam=%s AND thang=%s AND tvdi_mean IS NOT NULL;
            """
            cur.execute(query, (nam, thang))
            rows = cur.fetchall()
            return {
                str(r["ward_code"]).strip(): {
                    "tvdi_mean": r["tvdi"], "lst_mean": None, "ndvi_mean": None,
                }
                for r in rows
            }


def _resolve_code(code: str, geoms: dict):
    c = str(code).strip()
    return (geoms.get(c)
            or geoms.get(c.lower())
            or geoms.get(clean_ward_name(c)))


# =====================================================================
# 1. TIMELINE
# =====================================================================
@app.get("/api/city-series")
def city_series():
    with cursor() as cur:
        query = """
            WITH combined AS (
                SELECT nam, thang, 'thuc_te' AS loai, tvdi_mean::float AS tvdi
                FROM tvdi_by_ward
                WHERE tvdi_mean IS NOT NULL AND nam <= 2025

                UNION ALL

                SELECT nam, thang, 'du_bao' AS loai, tvdi_du_bao::float AS tvdi
                FROM tvdi_forecast
                WHERE tvdi_du_bao IS NOT NULL AND nam >= 2026
            )
            SELECT nam, thang, loai, AVG(tvdi)::float AS tvdi_mean
            FROM combined
            GROUP BY nam, thang, loai
            ORDER BY nam ASC, thang ASC;
        """
        cur.execute(query)
        rows = cur.fetchall()
        if not rows:
            raise HTTPException(404, "Không tìm thấy dữ liệu chuỗi thời gian trong CSDL.")
        return rows


# =====================================================================
# 2. MAP GEOJSON
# =====================================================================
@app.get("/api/map")
def map_data(
    nam: int = Query(2026, ge=2000, le=2100),
    thang: int = Query(1, ge=1, le=12),
    loai: str = Query("du_bao"),
):
    geoms = get_ward_geoms()
    stats_map = _fetch_metric_rows(nam, thang, loai)

    features = []
    unique_wards = {v["gid"]: v for v in geoms.values()}.values()

    for g in unique_wards:
        gid_code = g["gid"]
        w_name = g["name"]
        c_name = g["clean_name"]

        rec = (stats_map.get(gid_code)
               or stats_map.get(w_name)
               or stats_map.get(c_name)
               or {})

        tvdi = rec.get("tvdi_mean")
        lst = rec.get("lst_mean")
        ndvi = rec.get("ndvi_mean")
        lvl = classify(tvdi) if tvdi is not None else None

        features.append({
            "type": "Feature",
            "geometry": g["geometry"],
            "properties": {
                "ward_code": w_name,
                "ward_name": w_name,
                "area_km2": g["area_km2"],
                "tvdi_mean": tvdi,
                "lst_mean": lst,
                "ndvi_mean": ndvi,
                "level": lvl if lvl is not None else 2,
                "level_label": class_label(lvl) if lvl is not None else "Không có dữ liệu",
            },
        })

    return {"type": "FeatureCollection", "features": features}


# =====================================================================
# 3. SUMMARY
# =====================================================================
@app.get("/api/summary")
def summary(
    nam: int = Query(2026, ge=2000, le=2100),
    thang: int = Query(1, ge=1, le=12),
    loai: str = Query("du_bao"),
):
    geoms = get_ward_geoms()
    stats_map = _fetch_metric_rows(nam, thang, loai)

    if not stats_map:
        raise HTTPException(404, f"Không có dữ liệu thống kê cho năm {nam} tháng {thang}.")

    counts = [0] * len(CLASSES)
    total = 0.0
    items = []
    for code, rec in stats_map.items():
        v = rec.get("tvdi_mean")
        if v is None:
            continue
        counts[classify(v)] += 1
        total += v
        items.append((code, v))

    mean = total / len(items) if items else 0.0
    driest = sorted(items, key=lambda x: x[1], reverse=True)[:10]

    def resolve_name(code_str):
        info = _resolve_code(code_str, geoms)
        return info["name"] if info else code_str

    return {
        "mean": round(mean, 4),
        "level": classify(mean),
        "level_label": class_label(classify(mean)),
        "n_wards": len(items),
        "classes": [{"level": i, "label": CLASSES[i][1], "count": counts[i]}
                    for i in range(len(CLASSES))],
        "driest": [{
            "ward_code": code,
            "ward_name": resolve_name(code),
            "tvdi_mean": round(v, 4),
        } for code, v in driest],
    }


# =====================================================================
# 3b. RANKING PHƯỜNG/XÃ
# =====================================================================
@app.get("/api/ward-ranking")
def ward_ranking(
    nam: int = Query(2026, ge=2000, le=2100),
    thang: int = Query(1, ge=1, le=12),
    loai: str = Query("du_bao"),
    metric: str = Query("tvdi", pattern="^(tvdi|lst|ndvi)$"),
    limit: int = Query(200, ge=1, le=500),
):
    col = _metric_col(metric)
    order = "ASC" if metric == "ndvi" else "DESC"
    geoms = get_ward_geoms()

    with cursor() as cur:
        if loai == "du_bao" or nam >= 2026:
            if metric in ("lst", "ndvi"):
                raise HTTPException(400, "Chỉ số LST/NDVI hiện chưa hỗ trợ dữ liệu dự báo.")
            query = f"""
                SELECT TRIM(ward_code::text) AS code, tvdi_du_bao::float AS value
                FROM tvdi_forecast
                WHERE nam=%s AND thang=%s AND tvdi_du_bao IS NOT NULL
                ORDER BY value {order}
                LIMIT %s;
            """
            cur.execute(query, (nam, thang, limit))
        else:
            query = f"""
                SELECT TRIM(ward_code::text) AS code, {col}::float AS value
                FROM tvdi_by_ward
                WHERE nam=%s AND thang=%s AND {col} IS NOT NULL
                ORDER BY value {order}
                LIMIT %s;
            """
            cur.execute(query, (nam, thang, limit))
        rows = cur.fetchall()

    items = []
    for r in rows:
        info = _resolve_code(r["code"], geoms)
        items.append({
            "ward_code": r["code"],
            "ward_name": info["name"] if info else r["code"],
            "value": round(r["value"], 4) if r["value"] is not None else None,
            "metric": metric,
        })

    return {"metric": metric, "count": len(items), "items": items}


# =====================================================================
# 3c. FILTER PHƯỜNG THEO NGƯỠNG
# =====================================================================
class WardFilterRequest(BaseModel):
    metric: str = Field("tvdi", pattern="^(tvdi|lst|ndvi)$")
    operator: str = Field("gt", pattern="^(gt|gte|lt|lte|between)$")
    value: float
    value_max: Optional[float] = None


@app.post("/api/ward-filter")
def ward_filter(
    req: WardFilterRequest,
    nam: int = Query(2026, ge=2000, le=2100),
    thang: int = Query(1, ge=1, le=12),
    loai: str = Query("du_bao"),
):
    col = _metric_col(req.metric)
    geoms = get_ward_geoms()

    op_map = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    if req.operator == "between":
        if req.value_max is None:
            raise HTTPException(400, "Cần value_max cho toán tử 'between'.")
        where = f"{col} BETWEEN %s AND %s"
        params = [req.value, req.value_max]
    else:
        where = f"{col} {op_map[req.operator]} %s"
        params = [req.value]

    if loai == "du_bao" or nam >= 2026:
        if req.metric in ("lst", "ndvi"):
            raise HTTPException(400, "Chỉ số LST/NDVI hiện chưa hỗ trợ dữ liệu dự báo.")
        
        where_forecast = where.replace(col, "tvdi_du_bao")
        query = f"""
            SELECT TRIM(ward_code::text) AS code, tvdi_du_bao::float AS value
            FROM tvdi_forecast
            WHERE nam=%s AND thang=%s AND tvdi_du_bao IS NOT NULL AND {where_forecast}
            ORDER BY value DESC;
        """
        with cursor() as cur:
            cur.execute(query, [nam, thang, *params])
            rows = cur.fetchall()
    else:
        query = f"""
            SELECT TRIM(ward_code::text) AS code, {col}::float AS value
            FROM tvdi_by_ward
            WHERE nam=%s AND thang=%s AND {col} IS NOT NULL AND {where}
            ORDER BY value DESC;
        """
        with cursor() as cur:
            cur.execute(query, [nam, thang, *params])
            rows = cur.fetchall()

    items = []
    for r in rows:
        info = _resolve_code(r["code"], geoms)
        items.append({
            "ward_code": r["code"],
            "ward_name": info["name"] if info else r["code"],
            "value": round(r["value"], 4),
            "metric": req.metric,
        })

    return {"metric": req.metric, "count": len(items), "items": items}


# =====================================================================
# 4. WARD SERIES
# =====================================================================
@app.get("/api/ward/{ward_code}/series")
def ward_series(ward_code: str):
    w_str = str(ward_code).strip()
    c_str = clean_ward_name(w_str)

    with cursor() as cur:
        query = """
            WITH actual AS (
                SELECT nam, thang, 'thuc_te' AS loai, tvdi_mean::float AS tvdi_mean
                FROM tvdi_by_ward
                WHERE (LOWER(TRIM(ward_code::text)) = LOWER(%s) OR LOWER(TRIM(ward_code::text)) = LOWER(%s))
                  AND nam <= 2025 AND tvdi_mean IS NOT NULL
            ),
            forecast AS (
                SELECT nam, thang, 'du_bao' AS loai, tvdi_du_bao::float AS tvdi_mean
                FROM tvdi_forecast
                WHERE (LOWER(TRIM(ward_code::text)) = LOWER(%s) OR LOWER(TRIM(ward_code::text)) = LOWER(%s))
                  AND nam >= 2026 AND tvdi_du_bao IS NOT NULL
            )
            SELECT * FROM actual
            UNION ALL
            SELECT * FROM forecast
            ORDER BY nam, thang;
        """
        cur.execute(query, (w_str, c_str, w_str, c_str))
        series = cur.fetchall()

    if not series:
        raise HTTPException(404, f"Không tìm thấy chuỗi dữ liệu cho phường/xã: {ward_code}")

    geoms = get_ward_geoms()
    info = _resolve_code(ward_code, geoms)
    return {
        "ward": {
            "code": ward_code,
            "name": info["name"] if info else ward_code,
            "area_km2": info["area_km2"] if info else None,
        },
        "series": series,
    }


# =====================================================================
# 5. MODELS
# =====================================================================
@app.get("/api/models")
def models():
    with cursor() as cur:
        cur.execute("""
            SELECT mo_hinh, mae, rmse, r2, mape, rmse_kiem_dinh, so_voi_khi_hau
            FROM model_evaluation
            ORDER BY rmse ASC;
        """)
        res = cur.fetchall()
        if not res:
            raise HTTPException(404, "Bảng model_evaluation trong CSDL chưa có dữ liệu.")
        return res


# =====================================================================
# 6. EDGE R2
# =====================================================================
@app.get("/api/edge-r2")
def edge_r2():
    with cursor() as cur:
        cur.execute("""
            SELECT thang, AVG(r2_dry)::float AS r2_dry, AVG(r2_wet)::float AS r2_wet
            FROM tvdi_edge_params
            GROUP BY thang
            ORDER BY thang ASC;
        """)
        res = cur.fetchall()
        if not res:
            raise HTTPException(404, "Chưa có dữ liệu thông số đường cạnh trong CSDL.")
        return res


# =====================================================================
# 7. PREDICT (ADMIN ONLY)
# =====================================================================
class PredictRequest(BaseModel):
    ward_code: str
    horizon: int = Field(6, ge=1, le=12)


def get_model_bundle():
    global _model_bundle
    if _model_bundle is None:
        if not MODEL_PATH.exists():
            raise HTTPException(503, f"Chưa có file mô hình tại {MODEL_PATH}.")
        import joblib
        _model_bundle = joblib.load(MODEL_PATH)
    return _model_bundle


@app.post("/api/predict", dependencies=[Depends(require_admin)])
def predict(req: PredictRequest):
    """Chạy mô hình AI dự báo TVDI trực tiếp. CHỈ ADMIN."""
    ward_str = str(req.ward_code).strip()
    c_str = clean_ward_name(ward_str)

    hist = []
    with cursor() as cur:
        cur.execute(
            """
            SELECT nam, thang, tvdi_mean::float AS v FROM tvdi_by_ward
            WHERE (LOWER(TRIM(ward_code::text)) = LOWER(%s) OR LOWER(TRIM(ward_code::text)) = LOWER(%s))
              AND nam <= 2025 AND tvdi_mean IS NOT NULL
            ORDER BY nam, thang
            """,
            (ward_str, c_str),
        )
        hist = cur.fetchall()

    if len(hist) < N_LAGS:
        raise HTTPException(400, f"Dữ liệu lịch sử của {ward_str} không đủ {N_LAGS} tháng để chạy dự báo.")

    bundle = get_model_bundle()
    
    # Dự báo đệ quy từ mô hình
    import numpy as np
    preds = []
    buf = [h["v"] for h in hist[-N_LAGS:]]
    scaler = bundle.get("scaler")
    model = bundle["mo_hinh"]

    for _ in range(req.horizon):
        x = np.array(buf[-N_LAGS:]).reshape(1, -1)
        if scaler is not None:
            x = scaler.transform(x)
        y = float(model.predict(x)[0])
        preds.append(y)
        buf.append(y)

    last = hist[-1]
    result = []
    for k, v in enumerate(preds, start=1):
        y, m = add_months(last["nam"], last["thang"], k)
        result.append({
            "nam": y, "thang": m,
            "tvdi_du_bao": round(v, 4),
            "level_label": class_label(classify(v)),
        })

    with cursor(commit=True) as cur:
        cur.executemany(
            "INSERT INTO tvdi_forecast (ward_code, nam, thang, tvdi_du_bao, mo_hinh, loai) "
            "VALUES (%s, %s, %s, %s, %s, 'du_bao') ON CONFLICT DO NOTHING",
            [(ward_str, r["nam"], r["thang"], r["tvdi_du_bao"], MODEL_NAME) for r in result],
        )

    return {
        "ward_code": req.ward_code,
        "mo_hinh": MODEL_NAME,
        "saved": len(result),
        "predictions": result,
    }


# =====================================================================
# 8. HEALTH
# =====================================================================
@app.get("/api/health")
def health():
    with cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM public.phuong_xa_full")
        return {"ok": True, "wards_in_db": cur.fetchone()["n"]}


# Mount frontend static
if (ROOT / "frontend").exists():
    app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")