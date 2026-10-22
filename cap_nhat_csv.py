import pandas as pd

# 1. Đọc file CSV dự báo gốc
input_file = 'du_bao_phuong_xa.csv'
print(f"Đang đọc file {input_file}...")
df = pd.read_csv(input_file)

# 2. Áp dụng hiệu chỉnh baseline +0.05 và clamp trong khoảng [0, 1] theo chuẩn GEE
df['tvdi_du_bao'] = (df['tvdi_du_bao'] + 0.05).clip(0.0, 1.0).round(4)

# 3. Ghi đè trực tiếp lại file CSV (hoặc xuất ra file mới du_bao_phuong_xa.csv)
df.to_csv('du_bao_phuong_xa.csv', index=False, encoding='utf-8')
print("-> ĐÃ CẬP NHẬT THÀNH CÔNG FILE du_bao_phuong_xa.csv CHUẨN MÀU!")