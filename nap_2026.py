import csv
import psycopg2

# 1. Cấu hình kết nối PostgreSQL
DB_CONFIG = {
    "dbname": "tvdi_hcm",
    "user": "postgres",
    "password": ".",  # Mật khẩu dấu chấm của bạn
    "host": "localhost",
    "port": "5432"
}

# 2. HÀM HIỆU CHỈNH CHUẨN HOÁ BASELINE THEO GEE
# Cộng offset 0.05 và ép góc [0, 1] giống hàm .clamp(0, 1) trong GEE
OFFSET = 0.05

def adjust_tvdi_gee(raw_val):
    adjusted = raw_val + OFFSET
    # Giới hạn giá trị trong khoảng [0.0, 1.0] tương đương .clamp(0, 1) trong GEE
    return round(min(max(adjusted, 0.0), 1.0), 4)

try:
    print("Đang kết nối tới PostgreSQL...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Tự động chuyển kiểu dữ liệu ward_code sang VARCHAR(255) tránh lỗi độ dài
    cur.execute("ALTER TABLE public.tvdi_by_ward ALTER COLUMN ward_code TYPE VARCHAR(255);")
    
    # Dọn dẹp dữ liệu cũ năm 2026
    cur.execute("DELETE FROM public.tvdi_by_ward WHERE loai = 'du_bao' OR nam = 2026;")
    conn.commit()
    print("Đã dọn dẹp dữ liệu cũ năm 2026.")

    # Đọc file CSV và hiệu chỉnh dữ liệu
    csv_path = "du_bao_phuong_xa.csv"
    print(f"Đang đọc file {csv_path} và tính toán hiệu chỉnh baseline GEE...")
    
    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        records = []
        for row in reader:
            raw_tvdi = float(row['tvdi_du_bao'])
            final_tvdi = adjust_tvdi_gee(raw_tvdi) # Áp dụng công thức
            
            records.append((
                str(row['ward_code']),
                int(row['nam']),
                int(row['thang']),
                'du_bao',
                final_tvdi
            ))

    # Nạp 1.002 dòng đã hiệu chỉnh vào Database
    insert_query = """
        INSERT INTO public.tvdi_by_ward (ward_code, nam, thang, loai, tvdi_mean)
        VALUES (%s, %s, %s, %s, %s)
    """
    cur.executemany(insert_query, records)
    conn.commit()

    print(f"-> ĐÃ NẠP THÀNH CÔNG {len(records)} DÒNG DỰ BÁO 2026 ĐÃ HIỆU CHỈNH VÀO DATABASE!")

except Exception as e:
    print(f"❌ Lỗi nạp dữ liệu: {e}")
finally:
    if 'conn' in locals() and conn:
        cur.close()
        conn.close()