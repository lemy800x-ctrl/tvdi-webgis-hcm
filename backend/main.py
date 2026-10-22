
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="WebGIS TVDI TP.HCM")

# ============================================================
# 1. CẤU HÌNH
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Khai báo DATABASE_URL trong biến môi trường.
# Không ghi trực tiếp mật khẩu database vào mã nguồn.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")


class PredictRequest(BaseModel):
    ward_code: str
    horizon: int = 6


def get_db():
    if not DATABASE_URL:
        raise HTTPException(
            status_code=500,
            detail="Chưa cấu hình biến môi trường DATABASE_URL."
        )

    try:
        return psycopg2.connect(
            DATABASE_URL,
            cursor_factory=RealDictCursor
        )
    except Exception as e:
        print(f"Lỗi kết nối CSDL: {e}")
        raise HTTPException(
            status_code=500,
            detail="Không thể kết nối cơ sở dữ liệu."
        )


def get_data_type(year: int) -> str:
    """Chọn loại dữ liệu theo quy ước của hệ thống."""
    return "du_bao" if year >= 2026 else "thuc_te"


def get_level_label(value):
    """Phân loại mức TVDI."""
    if value is None:
        return "Không có dữ liệu"
    if value < 0.2:
        return "Rất ẩm"
    if value < 0.4:
        return "Ẩm"
    if value < 0.6:
        return "Trung bình"
    if value < 0.8:
        return "Khô"
    return "Rất khô"


# ============================================================
# 2. CHUỖI THỜI GIAN TOÀN TP.HCM
# ============================================================

@app.get("/api/city-series")
def get_city_series():
    conn = get_db()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    nam,
                    thang,
                    CASE
                        WHEN nam >= 2026 THEN 'du_bao'
                        ELSE 'thuc_te'
                    END AS loai,
                    AVG(tvdi_mean) AS tvdi_mean
                FROM tvdi_by_ward
                WHERE tvdi_mean IS NOT NULL
                  AND (
                      (nam < 2026 AND loai = 'thuc_te')
                      OR
                      (nam >= 2026 AND loai = 'du_bao')
                  )
                GROUP BY nam, thang
                ORDER BY nam ASC, thang ASC;
            """)

            return cur.fetchall()

    except HTTPException:
        raise
    except Exception as e:
        print(f"Lỗi /api/city-series: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ============================================================
# 3. BẢN ĐỒ GEOJSON
#    phuong_xa_full:
#      code, name, areakm2, geom
#    tvdi_by_ward:
#      ward_code, nam, thang, loai, tvdi_mean
# ============================================================

@app.get("/api/map")
def get_map_geojson(
    nam: int = Query(...),
    thang: int = Query(...)
):
    conn = get_db()
    loai = get_data_type(nam)

    try:
        with conn.cursor() as cur:
            cur.execute("""
                WITH tvdi_month AS (
                    SELECT
                        ward_code,
                        AVG(tvdi_mean) AS tvdi_mean
                    FROM tvdi_by_ward
                    WHERE nam = %s
                      AND thang = %s
                      AND loai = %s
                    GROUP BY ward_code
                )
                SELECT jsonb_build_object(
                    'type', 'FeatureCollection',
                    'features',
                    COALESCE(
                        jsonb_agg(
                            jsonb_build_object(
                                'type', 'Feature',
                                'geometry', ST_AsGeoJSON(w.geom)::jsonb,
                                'properties', jsonb_build_object(
                                    'ward_code', w.code,
                                    'ward_name', w.name,
                                    'tvdi_mean', t.tvdi_mean,
                                    'level_label',
                                        CASE
                                            WHEN t.tvdi_mean IS NULL
                                                THEN 'Không có dữ liệu'
                                            WHEN t.tvdi_mean < 0.2
                                                THEN 'Rất ẩm'
                                            WHEN t.tvdi_mean < 0.4
                                                THEN 'Ẩm'
                                            WHEN t.tvdi_mean < 0.6
                                                THEN 'Trung bình'
                                            WHEN t.tvdi_mean < 0.8
                                                THEN 'Khô'
                                            ELSE 'Rất khô'
                                        END
                                )
                            )
                        ),
                        '[]'::jsonb
                    )
                ) AS geojson
                FROM phuong_xa_full w
                LEFT JOIN tvdi_month t
                    ON t.ward_code = w.code;
            """, (nam, thang, loai))

            result = cur.fetchone()
            return result["geojson"]

    except HTTPException:
        raise
    except Exception as e:
        print(f"Lỗi /api/map: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ============================================================
# 4. THỐNG KÊ TVDI TOÀN THÀNH PHỐ
# ============================================================

@app.get("/api/summary")
def get_summary(
    nam: int = Query(...),
    thang: int = Query(...)
):
    conn = get_db()
    loai = get_data_type(nam)

    try:
        with conn.cursor() as cur:

            # Tổng hợp một giá trị cho mỗi phường/xã
            cur.execute("""
                WITH tvdi_month AS (
                    SELECT
                        ward_code,
                        AVG(tvdi_mean) AS tvdi_mean
                    FROM tvdi_by_ward
                    WHERE nam = %s
                      AND thang = %s
                      AND loai = %s
                      AND tvdi_mean IS NOT NULL
                    GROUP BY ward_code
                )
                SELECT
                    AVG(tvdi_mean) AS mean_val,
                    COUNT(*) FILTER (
                        WHERE tvdi_mean < 0.2
                    ) AS rat_am,
                    COUNT(*) FILTER (
                        WHERE tvdi_mean >= 0.2
                          AND tvdi_mean < 0.4
                    ) AS am,
                    COUNT(*) FILTER (
                        WHERE tvdi_mean >= 0.4
                          AND tvdi_mean < 0.6
                    ) AS trung_binh,
                    COUNT(*) FILTER (
                        WHERE tvdi_mean >= 0.6
                          AND tvdi_mean < 0.8
                    ) AS kho,
                    COUNT(*) FILTER (
                        WHERE tvdi_mean >= 0.8
                    ) AS rat_kho
                FROM tvdi_month;
            """, (nam, thang, loai))

            stats = cur.fetchone() or {}
            mean_val = stats.get("mean_val")
            mean_val = float(mean_val) if mean_val is not None else 0.0

            # Top 10 phường/xã có TVDI cao nhất
            cur.execute("""
                WITH tvdi_month AS (
                    SELECT
                        ward_code,
                        AVG(tvdi_mean) AS tvdi_mean
                    FROM tvdi_by_ward
                    WHERE nam = %s
                      AND thang = %s
                      AND loai = %s
                      AND tvdi_mean IS NOT NULL
                    GROUP BY ward_code
                )
                SELECT
                    w.code AS ward_code,
                    w.name AS ward_name,
                    t.tvdi_mean
                FROM tvdi_month t
                JOIN phuong_xa_full w
                    ON w.code = t.ward_code
                ORDER BY t.tvdi_mean DESC
                LIMIT 10;
            """, (nam, thang, loai))

            driest = cur.fetchall()

            classes = [
                {
                    "level": 0,
                    "label": "Rất ẩm",
                    "count": stats.get("rat_am") or 0
                },
                {
                    "level": 1,
                    "label": "Ẩm",
                    "count": stats.get("am") or 0
                },
                {
                    "level": 2,
                    "label": "Trung bình",
                    "count": stats.get("trung_binh") or 0
                },
                {
                    "level": 3,
                    "label": "Khô",
                    "count": stats.get("kho") or 0
                },
                {
                    "level": 4,
                    "label": "Rất khô",
                    "count": stats.get("rat_kho") or 0
                }
            ]

            return {
                "mean": mean_val,
                "level_label": get_level_label(mean_val),
                "classes": classes,
                "driest": driest
            }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Lỗi /api/summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ============================================================
# 5. CHUỖI THỜI GIAN THEO PHƯỜNG/XÃ
# ============================================================

@app.get("/api/ward/{ward_code}/series")
def get_ward_series(ward_code: str):
    conn = get_db()

    try:
        with conn.cursor() as cur:

            # Lấy thông tin phường/xã theo cột code
            cur.execute("""
                SELECT
                    code AS ward_code,
                    name AS name,
                    areakm2 AS area_km2
                FROM phuong_xa_full
                WHERE code = %s;
            """, (ward_code,))

            ward_info = cur.fetchone()

            if not ward_info:
                raise HTTPException(
                    status_code=404,
                    detail=f"Không tìm thấy phường/xã có mã {ward_code}."
                )

            # Chỉ lấy loại dữ liệu phù hợp với quy ước năm.
            # Tránh trả hai bản ghi thực tế/dự báo cho cùng một tháng.
            cur.execute("""
                SELECT
                    nam,
                    thang,
                    CASE
                        WHEN nam >= 2026 THEN 'du_bao'
                        ELSE 'thuc_te'
                    END AS loai,
                    AVG(tvdi_mean) AS tvdi_mean
                FROM tvdi_by_ward
                WHERE ward_code = %s
                  AND (
                      (nam < 2026 AND loai = 'thuc_te')
                      OR
                      (nam >= 2026 AND loai = 'du_bao')
                  )
                GROUP BY nam, thang
                ORDER BY nam ASC, thang ASC;
            """, (ward_code,))

            series = cur.fetchall()

            return {
                "ward": ward_info,
                "series": series
            }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Lỗi /api/ward/{ward_code}/series: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ============================================================
# 6. DỮ LIỆU DỰ BÁO
#    Lưu ý: API này đọc dự báo đã có trong database,
#    không tự huấn luyện hoặc chạy mô hình AI.
# ============================================================

@app.post("/api/predict")
def predict_tvdi(req: PredictRequest):
    if req.horizon < 1 or req.horizon > 24:
        raise HTTPException(
            status_code=400,
            detail="horizon phải nằm trong khoảng từ 1 đến 24."
        )

    conn = get_db()

    try:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    w.code AS ward_code,
                    w.name AS ward_name
                FROM phuong_xa_full w
                WHERE w.code = %s;
            """, (req.ward_code,))

            ward = cur.fetchone()

            if not ward:
                raise HTTPException(
                    status_code=404,
                    detail=f"Không tìm thấy phường/xã {req.ward_code}."
                )

            cur.execute("""
                SELECT
                    nam,
                    thang,
                    AVG(tvdi_mean) AS tvdi_du_bao
                FROM tvdi_by_ward
                WHERE ward_code = %s
                  AND nam >= 2026
                  AND loai = 'du_bao'
                  AND tvdi_mean IS NOT NULL
                GROUP BY nam, thang
                ORDER BY nam ASC, thang ASC
                LIMIT %s;
            """, (req.ward_code, req.horizon))

            predictions = cur.fetchall()

            for item in predictions:
                value = item.get("tvdi_du_bao")
                item["level_label"] = get_level_label(value)

            return {
                "ward_code": req.ward_code,
                "ward_name": ward["ward_name"],
                "predictions": predictions,
                "message": (
                    "Đã lấy dữ liệu dự báo được lưu trong cơ sở dữ liệu."
                    if predictions
                    else "Chưa có dữ liệu dự báo cho phường/xã này."
                )
            }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Lỗi /api/predict: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ============================================================
# 7. TRANG CHỦ VÀ FILE FRONTEND
# ============================================================

@app.get("/")
def read_root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")

    if os.path.exists(index_path):
        return FileResponse(index_path)

    return {
        "message": "WebGIS TVDI HCM API đang hoạt động!"
    }


if os.path.isdir(FRONTEND_DIR):
    app.mount(
        "/static",
        StaticFiles(directory=FRONTEND_DIR),
        name="static"
    )

    app.mount(
        "/frontend",
        StaticFiles(directory=FRONTEND_DIR),
        name="frontend"
    )

    app.mount(
        "/public",
        StaticFiles(directory=FRONTEND_DIR, html=True),
        name="public"
    )
