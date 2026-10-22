import os
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="WebGIS TVDI TP.HCM")

# Cấu hình CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. KẾT NỐI DATABASE NEON POSTGIS
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_NDjOWaZBu0C5@ep-cold-cloud-azly3g87.c-3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
)

def get_db():
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        print(f"Lỗi kết nối CSDL: {e}")
        return None

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

class PredictRequest(BaseModel):
    ward_code: str
    horizon: int = 6

# 2. CÁC API PHỤC VỤ WEBGIS

@app.get("/api/city-series")
def get_city_series():
    """Lấy chuỗi thời gian tháng/năm"""
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=500, detail="Lỗi kết nối cơ sở dữ liệu")
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT nam, thang, 
                       CASE WHEN nam >= 2026 THEN 'du_bao' ELSE 'thuc_te' END as loai,
                       AVG(tvdi_mean) as tvdi_mean
                FROM tvdi_by_ward
                GROUP BY nam, thang
                ORDER BY nam ASC, thang ASC;
            """)
            return cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/map")
def get_map_geojson(nam: int = Query(...), thang: int = Query(...)):
    """Lấy GeoJSON ranh giới kèm chỉ số TVDI"""
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=500, detail="Lỗi kết nối cơ sở dữ liệu")
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT jsonb_build_object(
                    'type', 'FeatureCollection',
                    'features', jsonb_agg(
                        jsonb_build_object(
                            'type', 'Feature',
                            'geometry', ST_AsGeoJSON(w.geom)::jsonb,
                            'properties', jsonb_build_object(
                                'ward_code', w.ward_code,
                                'ward_name', w.ward_name,
                                'tvdi_mean', t.tvdi_mean,
                                'level_label', t.level_label
                            )
                        )
                    )
                ) as geojson
                FROM phuong_xa_full w
                LEFT JOIN tvdi_by_ward t ON w.ward_code = t.ward_code AND t.nam = %s AND t.thang = %s;
            """, (nam, thang))
            res = cur.fetchone()
            return res['geojson'] if res and res['geojson'] else {"type": "FeatureCollection", "features": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/summary")
def get_summary(nam: int = Query(...), thang: int = Query(...)):
    """Thống kê trung bình và Top 10 nơi khô nhất"""
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=500, detail="Lỗi kết nối cơ sở dữ liệu")
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT AVG(tvdi_mean) as mean_val FROM tvdi_by_ward WHERE nam = %s AND thang = %s;
            """, (nam, thang))
            mean_row = cur.fetchone()
            mean_val = mean_row['mean_val'] if mean_row and mean_row['mean_val'] is not None else 0.0

            level_label = "Rất ẩm" if mean_val < 0.2 else ("Ẩm" if mean_val < 0.4 else ("Trung bình" if mean_val < 0.6 else ("Khô" if mean_val < 0.8 else "Rất khô")))

            cur.execute("""
                SELECT w.ward_code, w.ward_name, t.tvdi_mean
                FROM tvdi_by_ward t
                JOIN phuong_xa_full w ON t.ward_code = w.ward_code
                WHERE t.nam = %s AND t.thang = %s AND t.tvdi_mean IS NOT NULL
                ORDER BY t.tvdi_mean DESC
                LIMIT 10;
            """, (nam, thang))
            driest = cur.fetchall()

            cur.execute("""
                SELECT 
                    COUNT(CASE WHEN tvdi_mean < 0.2 THEN 1 END) as rat_am,
                    COUNT(CASE WHEN tvdi_mean >= 0.2 AND tvdi_mean < 0.4 THEN 1 END) as am,
                    COUNT(CASE WHEN tvdi_mean >= 0.4 AND tvdi_mean < 0.6 THEN 1 END) as trung_binh,
                    COUNT(CASE WHEN tvdi_mean >= 0.6 AND tvdi_mean < 0.8 THEN 1 END) as kho,
                    COUNT(CASE WHEN tvdi_mean >= 0.8 THEN 1 END) as rat_kho
                FROM tvdi_by_ward
                WHERE nam = %s AND thang = %s;
            """, (nam, thang))
            counts = cur.fetchone() or {}

            classes = [
                {"level": 0, "label": "Rất ẩm", "count": counts.get('rat_am', 0)},
                {"level": 1, "label": "Ẩm", "count": counts.get('am', 0)},
                {"level": 2, "label": "Trung bình", "count": counts.get('trung_binh', 0)},
                {"level": 3, "label": "Khô", "count": counts.get('kho', 0)},
                {"level": 4, "label": "Rất khô", "count": counts.get('rat_kho', 0)}
            ]

            return {
                "mean": mean_val,
                "level_label": level_label,
                "classes": classes,
                "driest": driest
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/ward/{ward_code}/series")
def get_ward_series(ward_code: str):
    """Chuỗi thời gian theo phường xã"""
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=500, detail="Lỗi kết nối cơ sở dữ liệu")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ward_code, ward_name as name, area_km2 FROM phuong_xa_full WHERE ward_code = %s;", (ward_code,))
            ward_info = cur.fetchone()
            if not ward_info:
                ward_info = {"ward_code": ward_code, "name": ward_code, "area_km2": 0}

            cur.execute("""
                SELECT nam, thang, tvdi_mean
                FROM tvdi_by_ward
                WHERE ward_code = %s
                ORDER BY nam ASC, thang ASC;
            """, (ward_code,))
            series = cur.fetchall()

            return {
                "ward": ward_info,
                "series": series
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.post("/api/predict")
def predict_tvdi(req: PredictRequest):
    """API Dự báo 6 tháng tới bằng AI"""
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=500, detail="Lỗi kết nối cơ sở dữ liệu")
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT nam, thang, tvdi_mean as tvdi_du_bao, level_label
                FROM tvdi_by_ward
                WHERE ward_code = %s AND nam >= 2026
                ORDER BY nam ASC, thang ASC
                LIMIT %s;
            """, (req.ward_code, req.horizon))
            predictions = cur.fetchall()
            return {"ward_code": req.ward_code, "predictions": predictions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# 3. TRANG CHỦ & PHỤC VỤ FILE FRONTEND

@app.get("/")
def read_root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "WebGIS TVDI HCM API đang hoạt động!"}

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="public")