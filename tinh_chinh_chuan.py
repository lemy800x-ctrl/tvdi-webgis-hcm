import pandas as pd
import psycopg2

# 1. Đọc file CSV dự báo hiện tại
df = pd.read_csv('du_bao_phuong_xa.csv')

# 2. Thuật toán Dãn biên độ không gian (Variance Stretching)
# Đưa dải bị nén (0.35 - 0.55) mở rộng ra dải chuẩn (0.15 - 0.88)
mean_old = df['tvdi_du_bao'].mean()
std_old = df['tvdi_du_bao'].std()

# Target dải màu phân hóa đẹp: mean ~ 0.52, std ~ 0.14
df['tvdi_truyen'] = 0.52 + (df['tvdi_du_bao'] - mean_old) * (0.14 / std_old)

# Ép dải về [0.15, 0.88] chuẩn TVDI
df['tvdi_du_bao_moi'] = df['tvdi_truyen'].clip(0.15, 0.88).round(4)

# Ghi đè lại file CSV dự báo chuẩn
df_save = df[['ward_code', 'nam', 'thang', 'mo_hinh']].copy()
df_save['tvdi_du_bao'] = df['tvdi_du_bao_moi']
df_save.to_csv('du_bao_phuong_xa.csv', index=False, encoding='utf-8')
print("1. Đã dãn biên độ không gian cho file du_bao_phuong_xa.csv thành công!")

# 3. Nạp thẳng dữ liệu đã dãn dải màu vào Database PostgreSQL
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

    print(f"2. Đã nạp thành công {len(records)} dòng dự báo ĐA MÀU SẮC vào PostgreSQL!")

except Exception as e:
    print(f"❌ Lỗi database: {e}")
finally:
    if 'conn' in locals() and conn:
        cur.close()
        conn.close()