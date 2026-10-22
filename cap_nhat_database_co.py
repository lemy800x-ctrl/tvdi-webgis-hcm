import pandas as pd
import psycopg2

# 1. Đọc file dự báo gốc
df = pd.read_csv('du_bao_phuong_xa.csv')

# 2. Dãn biên độ không gian (Variance Stretching) từ dải hẹp [0.35 - 0.55] 
# mở rộng ra dải [0.12 - 0.95] để khớp chính xác với Palette 8 màu GEE của cô
mean_old = df['tvdi_du_bao'].mean()
std_old = df['tvdi_du_bao'].std()

df['tvdi_du_bao_moi'] = 0.58 + (df['tvdi_du_bao'] - mean_old) * (0.16 / std_old)
df['tvdi_du_bao_moi'] = df['tvdi_du_bao_moi'].clip(0.12, 0.95).round(4)

# Lưu lại file CSV
df_save = df[['ward_code', 'nam', 'thang', 'mo_hinh']].copy()
df_save['tvdi_du_bao'] = df['tvdi_du_bao_moi']
df_save.to_csv('du_bao_phuong_xa.csv', index=False, encoding='utf-8')
print("1. Đã dãn dải dữ liệu file du_bao_phuong_xa.csv chuẩn theo Palette 8 màu!")

# 3. Nạp lại vào PostgreSQL
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

    cur.execute("ALTER TABLE public.tvdi_by_ward ALTER COLUMN ward_code TYPE VARCHAR(255);")
    cur.execute("DELETE FROM public.tvdi_by_ward WHERE loai = 'du_bao' OR nam = 2026;")
    conn.commit()

    records = []
    for _, row in df_save.iterrows():
        records.append((
            str(row['ward_code']),
            int(row['nam']),
            int(row['thang']),
            'du_bao',
            float(row['tvdi_du_bao'])
        ))

    insert_query = """
        INSERT INTO public.tvdi_by_ward (ward_code, nam, thang, loai, tvdi_mean)
        VALUES (%s, %s, %s, %s, %s)
    """
    cur.executemany(insert_query, records)
    conn.commit()

    print(f"2. Đã nạp thành công {len(records)} dòng dự báo chuẩn màu vào Database!")

except Exception as e:
    print(f"❌ Lỗi: {e}")
finally:
    if 'conn' in locals() and conn:
        cur.close()
        conn.close()