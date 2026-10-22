# Web theo dõi và dự báo khô hạn TVDI - TP.HCM (Đề tài 5, Nhóm 4)

Hệ thống gồm 3 lớp:

```
Trình duyệt (frontend/)  <->  Backend API (backend/main.py, FastAPI)  <->  PostgreSQL + PostGIS
                                      |
                              models/mo_hinh_tot_nhat.pkl  (mô hình AI)
```

Web có: bản đồ 168 phường/xã tô màu theo TVDI, thanh thời gian (thực tế 2016-2025 và dự báo),
thống kê từng tháng, biểu đồ từng phường/xã, nút "Dự báo 6 tháng tới bằng AI" (kết quả được lưu
vào bảng `prediction_log`), và tab so sánh các mô hình.

## Cấu trúc thư mục

```
tvdi_web/
├── db/
│   ├── 01_schema.sql           Tạo bảng
│   ├── 02_load_data.py         Nạp ranh giới phường/xã, TVDI (.parquet), thông số cạnh khô/ướt, so sánh mô hình
│   ├── 03_load_forecast.py     Nạp các file dự báo TVDI_duBao_thang*.tif
│   ├── 04_build_ward_stats.py  Tính TVDI trung bình theo từng phường/xã (Zonal Statistics)
│   └── common.py
├── backend/
│   ├── main.py                 API
│   └── helpers.py              Hàm phân mức khô hạn, dự báo đệ quy
├── frontend/                   index.html, style.css, app.js
├── models/                     Chép mo_hinh_tot_nhat.pkl vào đây
├── docker-compose.yml          (tùy chọn) chạy PostgreSQL bằng Docker
├── .env.example
└── requirements.txt
```

## Bước 0. Cài đặt (làm một lần)

1. Cài Python 3.10 trở lên.
2. Mở Command Prompt tại thư mục `tvdi_web`, chạy: `pip install -r requirements.txt`
   (nếu `rasterio` báo lỗi trên Windows, thử `pip install rasterio --only-binary :all:`).
3. Copy `.env.example` thành `.env`, sửa mật khẩu trong `DATABASE_URL`.

## Bước 1. Dựng PostgreSQL (bạn Văn làm)

**Cách A - Docker (gọn nhất):** đổi mật khẩu trong `docker-compose.yml` cho khớp `.env`, rồi chạy
`docker compose up -d`. Bảng tự được tạo.

**Cách B - Cài tay:** cài PostgreSQL + PostGIS (chọn PostGIS trong Stack Builder lúc cài), rồi:
```sql
CREATE USER tvdi_app WITH PASSWORD 'mat_khau_manh';
CREATE DATABASE tvdi_db OWNER tvdi_app;
```
Sau đó chạy `psql -U postgres -d tvdi_db -c "CREATE EXTENSION postgis;"` và
`psql -U tvdi_app -d tvdi_db -f db/01_schema.sql`.

## Bước 2. Nạp dữ liệu (chạy từ thư mục `tvdi_web`)

Chuẩn bị:
- **Ranh giới phường/xã:** tải bộ GeoJSON từ repo `thanglequoc/vietnamese-provinces-database` (release v4.1.0),
  giải nén, lấy thư mục `wards` của TP.HCM (thư mục tỉnh có mã 79). Mở thử 1 file trên geojson.io để chắc đúng.
- File từ bạn Khanh: `TVDI_2016_2025.parquet`, `TVDI_2016_2025_thong_so_bien.csv`.
- File từ bước huấn luyện: `ket_qua_so_sanh_mo_hinh.csv`, các file `TVDI_duBao_thang1.tif` ... `thang6.tif`.

Chạy lần lượt:
```
python db/02_load_data.py --wards-dir "D:\duong_dan\79_...\wards" --parquet TVDI_2016_2025.parquet --edge TVDI_2016_2025_thong_so_bien.csv --eval ket_qua_so_sanh_mo_hinh.csv
python db/03_load_forecast.py --dir . --base 2025-12 --model "Random Forest"
python db/04_build_ward_stats.py
```
- `--base 2025-12` là tháng cuối của dữ liệu thực tế. `thang1` sẽ được hiểu là 01/2026, `thang2` là 02/2026...
- Bước 02 nạp bảng TVDI rất lớn nên có thể mất vài chục phút. Bước 04 gán ô lưới vào phường/xã, mất vài phút.
- Cần có phường/xã (02) trước khi chạy 04.
- Nạp lại nhiều lần được: mỗi bước xóa dữ liệu cũ của bảng đó rồi nạp mới.

## Bước 3. Chạy web

Chép `mo_hinh_tot_nhat.pkl` vào `models/`, rồi:
```
uvicorn backend.main:app --reload
```
Mở http://localhost:8000. Kiểm tra nhanh kết nối CSDL ở http://localhost:8000/api/health (phải thấy `"wards": 168`).
Xem tài liệu API tự sinh ở http://localhost:8000/docs.

## Chia sẻ CSDL cho bạn Khanh

Bạn Khanh không cần giữ bản sao dữ liệu. Chỉ cần máy Khanh có source code này, sửa `.env`:
`DATABASE_URL=postgresql://khanh:<mật khẩu>@<IP máy bạn Văn>:5432/tvdi_db`.
Bạn Văn cần mở cổng 5432 cho mạng nội bộ (hoặc dùng Tailscale nếu khác mạng) và tạo tài khoản riêng cho Khanh.
Không mở cổng 5432 trực tiếp ra internet.

## Lưu ý quan trọng

- **Nút "Dự báo bằng AI" là xấp xỉ.** Mô hình được huấn luyện trên chuỗi của từng ô lưới 300 m, còn nút này đưa
  vào chuỗi TVDI trung bình của cả phường/xã (mượt hơn). Kết quả để minh họa luồng chạy AI và lưu CSDL.
  Bản đồ dự báo chính thức là dữ liệu trong `tvdi_forecast`, tính ở mức ô lưới.
- **Mức khô hạn** (Rất ẩm, Ẩm, Trung bình, Khô, Rất khô) dùng ngưỡng 0,2 / 0,4 / 0,6 / 0,8. Muốn đổi, sửa `CLASSES`
  trong `backend/helpers.py`.
- **Côn Đảo** nằm ngoài vùng tính TVDI (đã loại ở bước Earth Engine), nên đặc khu này hiện màu xám "Không có dữ liệu".
- **TVDI mùa mưa** (tháng 5-8) có R² của cạnh khô/ướt rất thấp, nên kém tin cậy hơn. Tab "Mô hình" trên web hiển thị điều này.
- **Phạm vi đề tài:** phần web/WebGIS có thể thuộc đề tài 6 theo bảng phân công. Hãy chốt với cô để tránh làm trùng.
- Backend dùng tên cột và tên bảng ở `db/01_schema.sql`. Nếu nhóm bên kia đổi tên, sửa đồng bộ trong `backend/main.py`.
