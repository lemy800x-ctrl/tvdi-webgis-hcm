"""
Nạp kết quả dự báo (các file TVDI_duBao_thang1.tif ... thang6.tif) vào bảng tvdi_forecast.

Ví dụ: dữ liệu thực tế kết thúc ở 12/2025 -> thang1 = 01/2026, thang2 = 02/2026 ...
    python db/03_load_forecast.py --dir . --base 2025-12 --model "Random Forest"
"""
import argparse
import io
import re
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import xy

from common import get_conn


def add_months(nam, thang, k):
    idx = nam * 12 + (thang - 1) + k
    return idx // 12, idx % 12 + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".", help="Thư mục chứa các file TVDI_duBao_thang*.tif")
    ap.add_argument("--base", required=True,
                    help="Tháng cuối cùng của dữ liệu thực tế, dạng 2025-12")
    ap.add_argument("--model", default="Random Forest",
                    help="Tên mô hình đã dùng để dự báo")
    args = ap.parse_args()

    base_y, base_m = (int(v) for v in args.base.split("-"))
    files = sorted(
        Path(args.dir).glob("TVDI_duBao_thang*.tif"),
        key=lambda p: int(re.search(r"thang(\d+)", p.stem).group(1)),
    )
    if not files:
        raise SystemExit(f"Không thấy file TVDI_duBao_thang*.tif trong {args.dir}")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for f in files:
                k = int(re.search(r"thang(\d+)", f.stem).group(1))
                nam, thang = add_months(base_y, base_m, k)

                with rasterio.open(f) as src:
                    arr = src.read(1)
                    transform = src.transform
                rows, cols = np.where(~np.isnan(arr))
                xs, ys = xy(transform, rows, cols)  # tọa độ tâm ô
                df = pd.DataFrame({
                    "x": np.round(np.asarray(xs), 6),
                    "y": np.round(np.asarray(ys), 6),
                    "nam": nam,
                    "thang": thang,
                    "tvdi_du_bao": arr[rows, cols],
                    "mo_hinh": args.model,
                })

                cur.execute(
                    "DELETE FROM tvdi_forecast WHERE nam=%s AND thang=%s AND mo_hinh=%s",
                    (nam, thang, args.model),
                )
                buf = io.StringIO()
                df.to_csv(buf, index=False, header=False)
                buf.seek(0)
                cur.copy_expert(
                    "COPY tvdi_forecast (x, y, nam, thang, tvdi_du_bao, mo_hinh) "
                    "FROM STDIN WITH (FORMAT csv)",
                    buf,
                )
                print(f"[forecast] {f.name} -> {thang:02d}/{nam}: {len(df):,} ô")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
