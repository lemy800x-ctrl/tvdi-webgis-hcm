"""
Nạp dữ liệu gốc vào PostgreSQL.

Chạy từ thư mục dự án (tvdi_web):
    python db/02_load_data.py --wards-dir <thư mục wards của TP.HCM> \
                              --parquet TVDI_2016_2025.parquet \
                              --edge TVDI_2016_2025_thong_so_bien.csv \
                              --eval ket_qua_so_sanh_mo_hinh.csv

Mỗi tham số đều tùy chọn: chỉ nạp phần nào bạn truyền vào.
Lưu ý: nạp lại sẽ XÓA dữ liệu cũ của bảng đó rồi nạp mới (tránh trùng dòng).
"""
import argparse
import io
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from common import get_conn


def copy_df(cur, df, table, columns):
    """Nạp DataFrame vào bảng bằng COPY (nhanh hơn INSERT hàng trăm lần)."""
    buf = io.StringIO()
    df[columns].to_csv(buf, index=False, header=False)
    buf.seek(0)
    cur.copy_expert(
        f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv)", buf
    )


def load_wards(conn, wards_dir):
    files = sorted(Path(wards_dir).rglob("*.geojson"))
    if not files:
        raise SystemExit(f"Không thấy file .geojson nào trong: {wards_dir}")
    n = 0
    with conn.cursor() as cur:
        for f in files:
            gj = json.loads(f.read_text(encoding="utf-8"))
            feats = gj["features"] if gj.get("type") == "FeatureCollection" else [gj]
            for ft in feats:
                p = ft.get("properties", {})
                code = str(p.get("code") or ft.get("id"))
                name = p.get("fullName") or p.get("name") or code
                cur.execute(
                    """
                    INSERT INTO wards (ward_code, ward_name, area_km2, geom)
                    SELECT %s, %s, %s, ST_Multi(g)
                    FROM (
                        SELECT ST_CollectionExtract(
                                 ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)), 3
                               ) AS g
                    ) s
                    WHERE NOT ST_IsEmpty(g)
                    ON CONFLICT (ward_code) DO UPDATE
                      SET ward_name = EXCLUDED.ward_name,
                          area_km2  = EXCLUDED.area_km2,
                          geom      = EXCLUDED.geom
                    """,
                    (code, name, p.get("areaKm2"), json.dumps(ft["geometry"])),
                )
                n += 1
    conn.commit()
    print(f"[wards] Đã nạp {n} phường/xã.")
    if n != 168:
        print("  ! Cảnh báo: TP.HCM mới có 168 phường/xã/đặc khu. "
              "Kiểm tra --wards-dir có đúng thư mục wards của TP.HCM không.")


def load_timeseries(conn, parquet_path):
    pf = pq.ParquetFile(parquet_path)
    rename = {"X": "x", "Y": "y", "NDVI": "ndvi", "LST": "lst", "TVDI": "tvdi"}
    cols = ["x", "y", "nam", "thang", "ndvi", "lst", "tvdi"]
    total = 0
    with conn.cursor() as cur:
        cur.execute("TRUNCATE tvdi_timeseries")
        for batch in pf.iter_batches(batch_size=500_000):
            df = batch.to_pandas().rename(columns=rename)
            copy_df(cur, df, "tvdi_timeseries", cols)
            total += len(df)
            print(f"[timeseries] đã nạp {total:,} dòng...")
    conn.commit()
    print(f"[timeseries] Xong: {total:,} dòng.")


def load_edge(conn, csv_path):
    df = pd.read_csv(csv_path)
    cols = ["nam", "thang", "a_dry", "b_dry", "r2_dry",
            "a_wet", "b_wet", "r2_wet", "n_bins_used"]
    with conn.cursor() as cur:
        cur.execute("TRUNCATE tvdi_edge_params")
        copy_df(cur, df, "tvdi_edge_params", cols)
    conn.commit()
    print(f"[edge] Đã nạp {len(df)} dòng thông số cạnh khô/ướt.")


def load_eval(conn, csv_path):
    df = pd.read_csv(csv_path).rename(columns={
        "MAE": "mae", "RMSE": "rmse", "R2": "r2", "MAPE": "mape"})
    cols = ["mo_hinh", "mae", "rmse", "r2", "mape"]
    with conn.cursor() as cur:
        cur.execute("TRUNCATE model_evaluation")
        copy_df(cur, df, "model_evaluation", cols)
    conn.commit()
    print(f"[eval] Đã nạp {len(df)} mô hình.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--wards-dir", help="Thư mục chứa các file .geojson phường/xã TP.HCM")
    ap.add_argument("--parquet", help="File TVDI_2016_2025.parquet")
    ap.add_argument("--edge", help="File TVDI_2016_2025_thong_so_bien.csv")
    ap.add_argument("--eval", help="File ket_qua_so_sanh_mo_hinh.csv")
    args = ap.parse_args()

    conn = get_conn()
    try:
        # Thứ tự: wards trước (các bảng khác tham chiếu tới nó)
        if args.wards_dir:
            load_wards(conn, args.wards_dir)
        if args.parquet:
            load_timeseries(conn, args.parquet)
        if args.edge:
            load_edge(conn, args.edge)
        if args.eval:
            load_eval(conn, args.eval)
    finally:
        conn.close()
