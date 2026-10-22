"""
Tính TVDI trung bình/nhỏ nhất/lớn nhất cho từng phường/xã (Zonal Statistics) và ghi vào tvdi_by_ward.

Bước 1: xác định mỗi ô lưới nằm trong phường/xã nào (bảng cells) - chỉ làm 1 lần.
Bước 2: gộp TVDI thực tế và TVDI dự báo theo (phường/xã, năm, tháng).

Chạy sau khi đã nạp wards, timeseries (02_load_data.py) và forecast (03_load_forecast.py):
    python db/04_build_ward_stats.py
"""
from common import get_conn

SQL_STEPS = [
    ("Tạo index phụ trợ",
     "CREATE INDEX IF NOT EXISTS ts_nam_thang ON tvdi_timeseries (nam, thang)"),

    ("Xóa bảng ô lưới cũ", "TRUNCATE cells"),

    ("Gán ô lưới -> phường/xã (point-in-polygon, có thể mất vài phút)",
     """
     INSERT INTO cells (x, y, ward_code)
     SELECT p.x, p.y, w.ward_code
     FROM (
         SELECT x, y FROM tvdi_timeseries GROUP BY x, y
         UNION
         SELECT x, y FROM tvdi_forecast GROUP BY x, y
     ) p
     LEFT JOIN LATERAL (
         SELECT ward_code
         FROM wards
         WHERE ST_Within(ST_SetSRID(ST_MakePoint(p.x, p.y), 4326), geom)
         ORDER BY ward_code
         LIMIT 1
     ) w ON TRUE
     """),

    ("Xóa thống kê cũ", "TRUNCATE tvdi_by_ward"),

    ("Tổng hợp TVDI thực tế theo phường/xã",
     """
     INSERT INTO tvdi_by_ward (ward_code, nam, thang, loai, tvdi_mean, tvdi_min, tvdi_max, n_cells)
     SELECT c.ward_code, t.nam, t.thang, 'thuc_te',
            AVG(t.tvdi), MIN(t.tvdi), MAX(t.tvdi), COUNT(*)
     FROM tvdi_timeseries t
     JOIN cells c ON c.x = t.x AND c.y = t.y
     WHERE c.ward_code IS NOT NULL AND t.tvdi IS NOT NULL
     GROUP BY c.ward_code, t.nam, t.thang
     """),

    ("Tổng hợp TVDI dự báo theo phường/xã",
     """
     INSERT INTO tvdi_by_ward (ward_code, nam, thang, loai, tvdi_mean, tvdi_min, tvdi_max, n_cells)
     SELECT c.ward_code, f.nam, f.thang, 'du_bao',
            AVG(f.tvdi_du_bao), MIN(f.tvdi_du_bao), MAX(f.tvdi_du_bao), COUNT(*)
     FROM tvdi_forecast f
     JOIN cells c ON c.x = f.x AND c.y = f.y
     WHERE c.ward_code IS NOT NULL AND f.tvdi_du_bao IS NOT NULL
     GROUP BY c.ward_code, f.nam, f.thang
     """),

    ("Cập nhật thống kê cho trình tối ưu truy vấn", "ANALYZE tvdi_by_ward"),
]


def main():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for title, sql in SQL_STEPS:
                print(f"- {title}...")
                cur.execute(sql)
            conn.commit()

            cur.execute("SELECT COUNT(*), COUNT(ward_code) FROM cells")
            total, inside = cur.fetchone()
            print(f"Ô lưới: {total:,} (nằm trong ranh giới phường/xã: {inside:,})")
            cur.execute("SELECT loai, COUNT(*), COUNT(DISTINCT ward_code) "
                        "FROM tvdi_by_ward GROUP BY loai ORDER BY loai")
            for loai, n, w in cur.fetchall():
                print(f"tvdi_by_ward [{loai}]: {n:,} dòng, {w} phường/xã")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
