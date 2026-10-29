import os
import glob
import pandas as pd
import numpy as np
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

def calculate_mape(y_true, y_pred):
    """Tính sai số phần trăm tuyệt đối trung bình (MAPE)"""
    y_true, y_pred = np.array(y_true), np.array(y_pred)
    # Tránh lỗi chia cho 0
    non_zero = y_true != 0
    return np.mean(np.abs((y_true[non_zero] - y_pred[non_zero]) / y_true[non_zero])) * 100

def evaluate_models(data_folder, output_file="ket_qua_so_sanh_mo_hinh.csv"):
    results = []

    # TRƯỜNG HỢP 1: Nếu dữ liệu dự báo của tất cả mô hình nằm chung 1 file CSV
    # (Ví dụ: file có các cột 'ward_code', 'nam', 'thang', 'mo_hinh', 'tvdi_du_bao', 'tvdi_thuc_te')
    combined_file = os.path.join(data_folder, "du_bao_tong_hop.csv")
    
    if os.path.exists(combined_file):
        df = pd.read_csv(combined_file)
        # Nhóm theo từng mô hình để tính chỉ số
        for model_name, group in df.groupby('mo_hinh'):
            y_true = group['tvdi_thuc_te']
            y_pred = group['tvdi_du_bao']
            
            rmse = np.sqrt(mean_squared_error(y_true, y_pred))
            mae = mean_absolute_error(y_true, y_pred)
            mse = mean_squared_error(y_true, y_pred)
            r2 = r2_score(y_true, y_pred)
            mape = calculate_mape(y_true, y_pred)
            
            results.append({
                'mo_hinh': model_name,
                'RMSE': round(rmse, 4),
                'MAE': round(mae, 4),
                'MSE': round(mse, 4),
                'R2': round(r2, 4),
                'MAPE_%': round(mape, 2)
            })
            
    # TRƯỜNG HỢP 2: Nếu mỗi mô hình là 1 file CSV riêng lẻ
    else:
        csv_files = glob.glob(os.path.join(data_folder, "*.csv"))
        for file_path in csv_files:
            file_name = os.path.basename(file_path)
            # Bỏ qua file kết quả nếu có
            if file_name == output_file:
                continue
                
            model_name = os.path.splitext(file_name)[0]
            df = pd.read_csv(file_path)
            
            # Đảm bảo file có đủ 2 cột dữ liệu thực tế và dự báo
            if 'y_true' in df.columns and 'y_pred' in df.columns:
                y_true = df['y_true']
                y_pred = df['y_pred']
                
                rmse = np.sqrt(mean_squared_error(y_true, y_pred))
                mae = mean_absolute_error(y_true, y_pred)
                mse = mean_squared_error(y_true, y_pred)
                r2 = r2_score(y_true, y_pred)
                mape = calculate_mape(y_true, y_pred)
                
                results.append({
                    'mo_hinh': model_name,
                    'RMSE': round(rmse, 4),
                    'MAE': round(mae, 4),
                    'MSE': round(mse, 4),
                    'R2': round(r2, 4),
                    'MAPE_%': round(mape, 2)
                })

    # Tạo DataFrame kết quả và sắp xếp theo RMSE tăng dần (mô hình tốt nhất lên đầu)
    df_results = pd.DataFrame(results)
    if not df_results.empty:
        df_results = df_results.sort_values(by='RMSE', ascending=True)
        # Xuất file CSV
        df_results.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"✅ Đã xuất kết quả so sánh mô hình thành công ra file: {output_file}")
        print("\n--- BẢNG KẾT QUẢ SO SÁNH ---")
        print(df_results.to_string(index=False))
    else:
        print("⚠️ Không tìm thấy cột dữ liệu phù hợp ('y_true'/'y_pred' hoặc 'mo_hinh'/'tvdi_du_bao') trong các file CSV.")

# --- CHẠY CHƯƠNG TRÌNH ---
if __name__ == "__main__":
    # Thay đường dẫn tới thư mục chứa các file CSV bạn tải từ Google Drive về
    FOLDER_PATH = "./data_drive" 
    evaluate_models(FOLDER_PATH)