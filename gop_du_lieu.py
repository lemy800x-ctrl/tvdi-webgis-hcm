import os
import glob
import pandas as pd

def gop_du_lieu_tvdi():
    # Tìm tất cả các file có dạng TVDI_phuongxa_*.csv
    files = sorted(glob.glob("TVDI_phuongxa_*.csv"))
    
    if not files:
        print("❌ Không tìm thấy file TVDI_phuongxa_*.csv nào trong thư mục!")
        return

    print(f"🔍 Tìm thấy {len(files)} file TVDI từng năm:")
    dfs = []
    for f in files:
        print(f"  ➔ Đang đọc {f}...")
        df = pd.read_csv(f)
        
        # Đổi tên cột về chuẩn nếu cần
        # (Chuyển tvdi_mean thành tvdi nếu file dùng tên tvdi_mean)
        if 'tvdi_mean' in df.columns and 'tvdi' not in df.columns:
            df = df.rename(columns={'tvdi_mean': 'tvdi'})
            
        dfs.append(df)

    # Gộp tất cả các năm thành 1 DataFrame
    df_full = pd.concat(dfs, ignore_index=True)
    
    # Sắp xếp lại theo tên phường, năm, tháng
    if {'fullname', 'nam', 'thang'}.issubset(df_full.columns):
        df_full = df_full.sort_values(by=['fullname', 'nam', 'thang'])

    # Xuất ra file tvdi_phuong_xa_full.csv
    file_out = "tvdi_phuong_xa_full.csv"
    df_full.to_csv(file_out, index=False, encoding="utf-8-sig")
    print(f"\n✅ Đã tạo thành công file: {file_out} ({len(df_full):,} dòng dữ liệu)")

if __name__ == "__main__":
    gop_du_lieu_tvdi()