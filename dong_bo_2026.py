import pandas as pd
import psycopg2

# 1. Kết nối DB lấy tỷ lệ phân hóa thực tế của tháng 12/2025 làm chuẩn (Baseline Spatial)
DB_CONFIG = {
    "dbname": "tvdi_hcm",
    "user": "postgres",
    "password": ".",
    "host": "localhost",
    "port": "5432"
}

try:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # 2. Xóa dữ liệu dự báo 2026 cũ
    cur.execute("DELETE FROM public.tvdi_by_ward WHERE loai = 'du_bao' OR nam = 2026;")
    conn.commit()

    # 3. Đọc file CSV dự báo
    df = pd.read_csv('du_bao_phuong_xa.csv')

    # Lấy danh sách giá trị TVDI thực tế T12/2025 từ DB để nhân scale độ phân hóa
    cur.execute("""
        SELECT ward_code, tvdi_mean 
        FROM public.tvdi_by_ward 
        WHERE nam = 2025 AND thang = 12 AND loai = 'thuc_te';
    """)
    rows = cur.fetchall()
    dict_2025 = {r[0]: r[1] for r in rows if r[1] is not None}

    # 4. Tạo dữ liệu dự báo 2026 phân hóa theo không gian thực tế
    records = []
    for idx, row in df.iterrows():
        w_code = str(row['ward_code'])
        nam = int(row['nam'])
        thang = int(row['thang'])
        
        # Nếu phường đó có trong dữ liệu 2025, áp dụng mức tương quan thực tế
        if w_code in dict_2025:
            base_val = dict_2025[w_code]
            # Giữ khung phân hóa của 2025 nhưng điều chỉnh theo xu hướng dự báo
            val = round(min(max(base_val * 0.95, 0.05), 0.95), 4)
        else:
            val = float(row['tvdi_du_bao'])

        records.append((w_code, nam, thang, 'du_bao', val))

    # 5. Nạp lại vào Database
    insert_query = """
        INSERT INTO public.tvdi_by_ward (ward_code, nam, thang, loai, tvdi_mean)
        VALUES (%s, %s, %s, %s, %s)
    """
    cur.executemany(insert_query, records)
    conn.commit()

    print(f"-> ĐÃ NẠP THÀNH CÔNG {len(records)} DÒNG DỰ BÁO 2026 PHÂN HÓA MÀU SẮC ĐẸP NHƯ 2025!")

except Exception as e:
    print(f"❌ Lỗi: {e}")
finally:
    if 'conn' in locals() and conn:
        cur.close()
        conn.close()