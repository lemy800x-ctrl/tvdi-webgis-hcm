"""
BƯỚC 5 - Nạp dữ liệu TVDI thực tế (Tự động nhận diện mọi định dạng cột CSV 10 năm) vào PostgreSQL.

Cài thư viện:  pip install pandas psycopg2-binary python-dotenv
Chạy lệnh:     python 05_nap_postgres.py
"""
import argparse
import glob
import io
import os

import pandas as pd
from dotenv import find_dotenv, load_dotenv


def ghi_bang(cur, ten_bang, df):
    cur.execute(f"TRUNCATE {ten_bang}")
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False)
    buf.seek(0)
    cur.copy_expert(f"COPY {ten_bang} ({', '.join(df.columns)}) FROM STDIN WITH (FORMAT csv)", buf)
    print(f"  ✅ {ten_bang}: {len(df):,} dòng")


def tim_cot(df, cac_ten_kha_thi):
    """Tìm cột phù hợp nhất trong DataFrame không phân biệt chữ hoa/thường."""
    cols_lower = {str(c).strip().lower(): c for c in df.columns}
    for ten in cac_ten_kha_thi:
        if ten.lower() in cols_lower:
            return cols_lower[ten.lower()]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dubao", default="du_bao_phuong_xa.csv")
    ap.add_argument("--models", default="ket_qua_so_sanh_mo_hinh.csv")
    ap.add_argument("--edge", default="thong_so_bien_full.csv")
    args = ap.parse_args()

    import psycopg2
    load_dotenv(find_dotenv(usecwd=True))
    url = os.getenv("DATABASE_URL", "postgresql://postgres:hihi@localhost:5432/tvdi_hcm")

    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            # 1. Bỏ constraint khóa ngoại cũ
            cur.execute("""
                ALTER TABLE IF EXISTS public.tvdi_by_ward 
                DROP CONSTRAINT IF EXISTS tvdi_by_ward_ward_code_fkey;
            """)

            # 2. Kiểm tra danh sách cột thực tế trong phuong_xa_full
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'phuong_xa_full';
            """)
            cols = {r[0].lower() for r in cur.fetchall()}

            name_candidates = []
            for col in ["fullname", "name", "ward_name", "ten_phuong", "ten_xa", "f_name"]:
                if col in cols:
                    name_candidates.append(f"NULLIF({col}::text, '')")
            name_candidates.append("''")
            
            name_sql = f"LOWER(TRIM(COALESCE({', '.join(name_candidates)})))"

            # Đọc ánh xạ Tên Phường/Xã -> Mã gid
            cur.execute(f"SELECT gid::text AS ward_code, {name_sql} AS name_clean FROM public.phuong_xa_full;")
            name_to_gid = {r[1]: r[0] for r in cur.fetchall() if r[1]}

            cur.execute("SELECT gid::text FROM public.phuong_xa_full")
            valid_gids = {r[0] for r in cur.fetchall()}

            def map_to_ward_code(val):
                val_str = str(val).strip()
                if val_str in valid_gids:
                    return val_str
                val_lower = val_str.lower()
                if val_lower in name_to_gid:
                    return name_to_gid[val_lower]
                return None

            # 3. Quét TẤT CẢ các file TVDI_phuongxa_*.csv & tvdi_phuong_xa_*.csv
            csv_files = glob.glob("TVDI_phuongxa_*.csv") + glob.glob("tvdi_phuong_xa_*.csv") + glob.glob("tvdi_phuong_xa.csv")
            csv_files = list(set(csv_files))

            if csv_files:
                print(f"-> Tìm thấy {len(csv_files)} file CSV dữ liệu thực tế. Đang gộp dữ liệu:")
                list_dfs = []
                for f in sorted(csv_files):
                    print(f"   + Đang đọc: {f}")
                    df_temp = pd.read_csv(f)
                    
                    # Tìm tên cột linh hoạt
                    col_ward = tim_cot(df_temp, ["ward_code", "fullname", "name", "ten_phuong", "ten_px", "ward_name"]) or df_temp.columns[0]
                    col_tvdi = tim_cot(df_temp, ["tvdi", "tvdi_mean", "tvdi_du_bao", "mean", "value"])
                    col_nam = tim_cot(df_temp, ["nam", "year"])
                    col_thang = tim_cot(df_temp, ["thang", "month"])
                    col_pixel = tim_cot(df_temp, ["n_pixel", "n_cells", "count", "pixels"])

                    if not col_tvdi:
                        print(f"     ! Bỏ qua {f} do không tìm thấy cột chứa giá trị TVDI.")
                        continue

                    df_temp["mapped_code"] = df_temp[col_ward].apply(map_to_ward_code)
                    df_temp = df_temp.dropna(subset=["mapped_code"])

                    df_clean = pd.DataFrame({
                        "ward_code": df_temp["mapped_code"],
                        "nam": df_temp[col_nam].astype(int) if col_nam else 2024,
                        "thang": df_temp[col_thang].astype(int) if col_thang else 1,
                        "loai": "thuc_te",
                        "tvdi_mean": pd.to_numeric(df_temp[col_tvdi], errors="coerce"),
                        "tvdi_min": pd.NA,
                        "tvdi_max": pd.NA,
                        "n_cells": pd.to_numeric(df_temp[col_pixel], errors="coerce") if col_pixel else pd.NA,
                    })
                    list_dfs.append(df_clean)

                if list_dfs:
                    df_thuc_te = pd.concat(list_dfs, ignore_index=True)

                    parts = [df_thuc_te]
                    # Thêm dữ liệu dự báo AI nếu có file du_bao_phuong_xa.csv
                    if os.path.exists(args.dubao):
                        print(f"   + Đang đọc dữ liệu dự báo: {args.dubao}")
                        b = pd.read_csv(args.dubao)
                        col_b_ward = tim_cot(b, ["ward_code", "fullname", "name", "ten_phuong"]) or b.columns[0]
                        col_b_tvdi = tim_cot(b, ["tvdi_du_bao", "tvdi", "tvdi_mean"]) or b.columns[1]
                        col_b_nam = tim_cot(b, ["nam", "year"])
                        col_b_thang = tim_cot(b, ["thang", "month"])
                        
                        b["mapped_code"] = b[col_b_ward].apply(map_to_ward_code)
                        b = b.dropna(subset=["mapped_code"])

                        parts.append(pd.DataFrame({
                            "ward_code": b["mapped_code"],
                            "nam": b[col_b_nam].astype(int) if col_b_nam else 2026,
                            "thang": b[col_b_thang].astype(int) if col_b_thang else 1,
                            "loai": "du_bao",
                            "tvdi_mean": pd.to_numeric(b[col_b_tvdi], errors="coerce"),
                            "tvdi_min": pd.NA,
                            "tvdi_max": pd.NA,
                            "n_cells": pd.NA,
                        }))

                    df_by_ward = pd.concat(parts, ignore_index=True)
                    df_by_ward = df_by_ward.dropna(subset=["tvdi_mean"]).drop_duplicates(["ward_code", "nam", "thang", "loai"])
                    
                    ghi_bang(cur, "tvdi_by_ward", df_by_ward[["ward_code", "nam", "thang", "loai", "tvdi_mean", "tvdi_min", "tvdi_max", "n_cells"]])

            # 4. Nạp model_evaluation
            if os.path.exists(args.models):
                df_m = pd.read_csv(args.models).rename(columns={"MAE": "mae", "RMSE": "rmse", "R2": "r2", "MAPE": "mape"})
                ghi_bang(cur, "model_evaluation", df_m[["mo_hinh", "mae", "rmse", "r2", "mape"]])

            # 5. Nạp tvdi_edge_params
            if os.path.exists(args.edge):
                df_e = pd.read_csv(args.edge)
                if "ok" in df_e.columns:
                    df_e = df_e[df_e["ok"] == 1]
                
                df_e["nam"] = df_e["nam"].astype(int)
                df_e["thang"] = df_e["thang"].astype(int)
                
                cols_edge = ["nam", "thang", "a_dry", "b_dry", "r2_dry", "a_wet", "b_wet", "r2_wet"]
                if "n_bins_used" in df_e.columns:
                    cols_edge.append("n_bins_used")
                
                ghi_bang(cur, "tvdi_edge_params", df_e[cols_edge])

        conn.commit()
        print("\n🎉 Hoàn thành gộp và nạp toàn bộ dữ liệu 10 năm vào PostgreSQL!")
        print("Bây giờ bạn hãy ra trình duyệt http://localhost:8000 và bấm Ctrl+F5.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()