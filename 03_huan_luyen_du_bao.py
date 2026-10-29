"""
BƯỚC 3 - Huấn luyện, so sánh mô hình, KIỂM CHỨNG bằng dữ liệu thật 2026 và dự báo tương lai.

Vì sao làm khác bản cũ:
  TVDI của từng phường/xã rất theo mùa và mỗi phường/xã có mức nền riêng. Nếu chỉ đưa 6 tháng gần nhất
  vào mô hình thì mô hình không học được gì hơn "đoán bằng trung bình" (R² âm). Ở đây:
    1. Tính "khí hậu" = TVDI trung bình nhiều năm của TỪNG phường/xã theo TỪNG tháng trong năm
       (chỉ từ giai đoạn huấn luyện, không nhìn tương lai).
    2. Mô hình học PHẦN LỆCH so với khí hậu (dị thường), dùng: dị thường 6 tháng trước, dị thường cùng
       tháng năm trước, tháng trong năm (sin/cos), khí hậu tháng cần dự báo, mức nền của phường/xã.
    3. So sánh công bằng với 2 mô hình cơ sở: "giữ nguyên tháng trước" và "khí hậu theo tháng".
  KHÔNG có bước nào chỉnh sửa kết quả dự báo cho "đẹp". Nếu mô hình không hơn khí hậu thì báo cáo đúng như vậy.

Chia thời gian (không xáo trộn):
    huấn luyện : đến 12/2023        kiểm định : 2024 - 2025        kiểm tra (tương lai thật): 2026
Kiểm chứng: huấn luyện đến 12/2025, dự báo đệ quy các tháng 2026 rồi so với TVDI thật của đúng các tháng đó.
Dự báo tương lai: huấn luyện lại trên toàn bộ dữ liệu, dự báo HORIZON tháng tiếp theo.

Chạy:   python 03_huan_luyen_du_bao.py tvdi_phuong_xa_full.csv
Cài:    pip install numpy pandas scikit-learn
Tùy chọn: pip install xgboost tensorflow   (không có thì tự bỏ qua XGBoost/LSTM/GRU)

Đầu ra:
    du_bao_phuong_xa.csv            fullname, nam, thang, tvdi_du_bao, mo_hinh, loai (du_bao | kiem_chung)
    ket_qua_so_sanh_mo_hinh.csv     chỉ số trên giai đoạn kiểm tra 2026 (một bước, dùng TVDI thật làm đầu vào)
    kiem_chung_tom_tat.csv          sai số theo số tháng dự báo trước (đệ quy), so với khí hậu
"""
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import BayesianRidge, LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import ParameterGrid
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

try:
    import xgboost as xgb
except ImportError:
    xgb = None
try:
    from tensorflow.keras.callbacks import EarlyStopping
    from tensorflow.keras.layers import GRU, LSTM, Dense, Dropout
    from tensorflow.keras.models import Sequential
except ImportError:
    Sequential = None

# ====================== CẤU HÌNH ======================
FILE_VAO = "tvdi_phuong_xa_full.csv"
N_LAGS = 6            # số tháng dị thường liền trước đưa vào mô hình bảng
SEQ_LEN = 12          # độ dài chuỗi cho LSTM/GRU
HORIZON = 6           # dự báo tương lai bao nhiêu tháng
TRAIN_END = (2023, 12)
VAL_END = (2025, 12)
MIN_OBS = 24          # phường/xã có < 24 tháng hợp lệ trong giai đoạn huấn luyện thì bỏ
KHI_HAU = "Khí hậu theo tháng"
PERSIST = "Giữ nguyên tháng trước"


# ====================== 1. ĐỌC DỮ LIỆU, BỎ ẢNH HỎNG ======================
def doc_ma_tran(path):
    df = pd.read_csv(path, dtype={"fullname": str})
    df["nam"], df["thang"] = df["nam"].astype(int), df["thang"].astype(int)
    hop_le = (df["trang_thai"] == "OK") & df["tvdi"].notna()
    print(f"Bỏ {int((~hop_le).sum()):,} / {len(df):,} dòng ảnh hỏng hoặc thiếu ({(~hop_le).mean():.1%}) khỏi học máy.")
    df.loc[~hop_le, "tvdi"] = np.nan

    keys = sorted(set(zip(df["nam"], df["thang"])))
    (y0, m0), (y1, m1) = keys[0], keys[-1]
    months = [(y, m) for y in range(y0, y1 + 1) for m in range(1, 13) if (y0, m0) <= (y, m) <= (y1, m1)]
    midx = {k: i for i, k in enumerate(months)}
    wards = sorted(df["fullname"].unique())
    widx = {w: i for i, w in enumerate(wards)}
    Y = np.full((len(wards), len(months)), np.nan)
    wi = df["fullname"].map(widx).to_numpy()
    mi = np.array([midx[(a, b)] for a, b in zip(df["nam"], df["thang"])])
    Y[wi, mi] = df["tvdi"].to_numpy()
    return Y, wards, months


def khi_hau(Y, months, t_end):
    """TVDI trung bình của từng phường/xã theo từng tháng trong năm, chỉ dùng các tháng chỉ số <= t_end."""
    n = Y.shape[0]
    C = np.full((n, 12), np.nan)
    moy = np.array([m - 1 for _, m in months])
    for k in range(12):
        sel = [t for t in range(t_end + 1) if moy[t] == k]
        if sel:
            C[:, k] = np.nanmean(Y[:, sel], axis=1)
    mean_w = np.nanmean(Y[:, : t_end + 1], axis=1)
    C = np.where(np.isnan(C), mean_w[:, None], C)
    return C, mean_w


# ====================== 2. ĐẶC TRƯNG ======================
def moy_ext(months, T):
    """Tháng trong năm (0..11) cho T cột, kể cả các tháng tương lai chưa có trong 'months'."""
    out = [m - 1 for _, m in months]
    y, m = months[-1]
    while len(out) < T:
        m += 1
        if m > 12:
            m, y = 1, y + 1
        out.append(m - 1)
    return np.array(out[:T])


def tao_dac_trung(A, C, mean_w, moy, t):
    """Đặc trưng bảng + chuỗi cho mọi phường/xã tại tháng chỉ số t (A = ma trận dị thường)."""
    n = A.shape[0]
    z = np.zeros(n)
    cols = [np.nan_to_num(A[:, t - k]) if t - k >= 0 else z for k in range(1, N_LAGS + 1)]
    ly = np.nan_to_num(A[:, t - 12]) if t - 12 >= 0 else z
    ang = 2 * np.pi * moy[t] / 12
    tab = np.column_stack(cols + [ly, C[:, moy[t]], mean_w, np.full(n, np.sin(ang)), np.full(n, np.cos(ang))])

    seq = np.zeros((n, SEQ_LEN, 3))
    for j in range(SEQ_LEN):
        tt = t - SEQ_LEN + j
        if tt >= 0:
            seq[:, j, 0] = np.nan_to_num(A[:, tt])
            a = 2 * np.pi * moy[tt] / 12
            seq[:, j, 1], seq[:, j, 2] = np.sin(a), np.cos(a)
    return tab, seq


def dung_tap(Y, C, mean_w, moy, t_from, t_to):
    """Tập (X, chuỗi, y dị thường, chỉ số tháng) cho các tháng t_from..t_to, chỉ giữ ô có TVDI thật."""
    A = Y - C[:, moy[: Y.shape[1]]]
    Xs, Ss, ys, ts, ws = [], [], [], [], []
    for t in range(t_from, t_to + 1):
        tab, seq = tao_dac_trung(A, C, mean_w, moy, t)
        ok = ~np.isnan(A[:, t])
        Xs.append(tab[ok]); Ss.append(seq[ok]); ys.append(A[ok, t])
        ts.append(np.full(ok.sum(), t)); ws.append(np.where(ok)[0])
    return np.vstack(Xs), np.concatenate([[]] if False else Ss) if False else np.concatenate(Ss), \
        np.concatenate(ys), np.concatenate(ts), np.concatenate(ws)


# ====================== 3. MÔ HÌNH ======================
class KhongHoc:
    """Dị thường = 0, tức dự báo bằng đúng khí hậu."""
    def fit(self, *a, **k): return self
    def predict(self, X, S): return np.zeros(len(X))


class Bang:
    """Bọc mô hình scikit-learn/XGBoost: chuẩn hóa chỉ học trên tập huấn luyện."""
    def __init__(self, m): self.m, self.sc = m, StandardScaler()
    def fit(self, X, S, y, Xv=None, Sv=None, yv=None):
        Xs = self.sc.fit_transform(X)
        if xgb is not None and isinstance(self.m, xgb.XGBRegressor) and Xv is not None:
            self.m.fit(Xs, y, eval_set=[(self.sc.transform(Xv), yv)], verbose=False)
        else:
            self.m.fit(Xs, y)
        return self
    def predict(self, X, S): return np.asarray(self.m.predict(self.sc.transform(X))).ravel()


class Chuoi:
    """LSTM / GRU trên chuỗi 12 tháng [dị thường, sin tháng, cos tháng]."""
    def __init__(self, loai):
        Lop = LSTM if loai == "LSTM" else GRU
        self.m = Sequential([Lop(32, input_shape=(SEQ_LEN, 3)), Dropout(0.2), Dense(1)])
        self.m.compile(optimizer="adam", loss="mse")
    def fit(self, X, S, y, Xv=None, Sv=None, yv=None):
        cb = [EarlyStopping(patience=5, restore_best_weights=True)] if Sv is not None else []
        self.m.fit(S, y, validation_data=(Sv, yv) if Sv is not None else None, epochs=40,
                   batch_size=128, verbose=0, callbacks=cb)
        return self
    def predict(self, X, S): return self.m.predict(S, verbose=0).ravel()


def tao_mo_hinh(ten, rf_params=None):
    if ten == KHI_HAU: return KhongHoc()
    if ten == "Linear Regression": return Bang(LinearRegression())
    if ten == "Bayesian Ridge": return Bang(BayesianRidge())
    if ten == "Random Forest":
        return Bang(RandomForestRegressor(random_state=42, n_jobs=-1, **(rf_params or {"n_estimators": 150, "max_depth": 10, "min_samples_leaf": 5})))
    if ten == "XGBoost":
        return Bang(xgb.XGBRegressor(n_estimators=200, max_depth=3, learning_rate=0.05, random_state=42,
                                     early_stopping_rounds=20, eval_metric="rmse"))
    if ten in ("LSTM", "GRU"): return Chuoi(ten)
    raise ValueError(ten)


def danh_sach_mo_hinh():
    ds = ["Linear Regression", "Bayesian Ridge", "Random Forest"]
    if xgb is not None: ds.append("XGBoost")
    else: print("(Bỏ qua XGBoost: chưa cài xgboost)")
    if Sequential is not None: ds += ["LSTM", "GRU"]
    else: print("(Bỏ qua LSTM/GRU: chưa cài tensorflow)")
    return ds


# ====================== 4. ĐÁNH GIÁ ======================
def chi_so(y, p):
    ok = ~np.isnan(y) & ~np.isnan(p)
    y, p = y[ok], p[ok]
    m = np.abs(y) > 0.05
    return {"MAE": mean_absolute_error(y, p), "RMSE": float(np.sqrt(mean_squared_error(y, p))),
            "R2": r2_score(y, p), "MAPE": float(np.mean(np.abs((y[m] - p[m]) / y[m])) * 100) if m.any() else np.nan}


def du_bao_mot_buoc(mh, Y, C, mean_w, moy, ts, ws, tab, seq):
    """TVDI dự báo = khí hậu + dị thường dự đoán (một bước, đầu vào là TVDI thật)."""
    return np.clip(C[ws, moy[ts]] + mh.predict(tab, seq), 0, 1)


# ====================== 5. DỰ BÁO ĐỆ QUY ======================
def du_bao_de_quy(mh, Y, C, mean_w, moy, t_bat_dau, so_buoc):
    """Dự báo từng tháng một; tháng sau dùng dị thường vừa dự báo làm đầu vào. Trả về (so_buoc, n) TVDI."""
    n, T0 = Y.shape
    T = t_bat_dau + so_buoc
    A = np.full((n, max(T, T0)), np.nan)
    A[:, :t_bat_dau] = Y[:, :t_bat_dau] - C[:, moy[:t_bat_dau]]      # chỉ phần đã biết
    out = []
    for s in range(so_buoc):
        t = t_bat_dau + s
        tab, seq = tao_dac_trung(A, C, mean_w, moy, t)
        an = mh.predict(tab, seq)
        A[:, t] = an
        out.append(np.clip(C[:, moy[t]] + an, 0, 1))
    return np.array(out)


# ====================== CHƯƠNG TRÌNH CHÍNH ======================
def main(path=FILE_VAO):
    Y, wards, months = doc_ma_tran(path)
    T = Y.shape[1]
    midx = {k: i for i, k in enumerate(months)}
    if TRAIN_END not in midx or VAL_END not in midx:
        raise SystemExit("Dữ liệu chưa tới tháng chia tập (TRAIN_END/VAL_END). Kiểm tra file đầu vào.")
    t_tr, t_va = midx[TRAIN_END], midx[VAL_END]
    moy = moy_ext(months, T + HORIZON + 12)

    # Bỏ phường/xã có quá ít tháng hợp lệ trong giai đoạn huấn luyện
    du = np.sum(~np.isnan(Y[:, : t_tr + 1]), axis=1) >= MIN_OBS
    print(f"Giữ {du.sum()} / {len(wards)} phường/xã (đủ ≥ {MIN_OBS} tháng hợp lệ để học).")
    Y, wards = Y[du], [w for w, k in zip(wards, du) if k]
    n = len(wards)

    co_test = t_va < T - 1
    t_te_from = t_va + 1 if co_test else t_tr + 1
    t_te_to = T - 1 if co_test else t_va
    if not co_test:
        print("! Chưa có dữ liệu sau VAL_END: dùng giai đoạn kiểm định làm kiểm tra (kém khách quan).")

    # ---------- Giai đoạn 1: chọn mô hình (khí hậu chỉ từ giai đoạn huấn luyện) ----------
    C1, w1 = khi_hau(Y, months, t_tr)
    Xtr, Str, ytr, _, _ = dung_tap(Y, C1, w1, moy, N_LAGS, t_tr)
    Xva, Sva, yva, tva, wva = dung_tap(Y, C1, w1, moy, t_tr + 1, t_va)
    Xte, Ste, yte, tte, wte = dung_tap(Y, C1, w1, moy, t_te_from, t_te_to)
    print(f"Mẫu: huấn luyện {len(ytr):,} | kiểm định {len(yva):,} | kiểm tra {len(yte):,}")

    thuc_va = Y[wva, tva]
    thuc_te = Y[wte, tte]
    ket_qua, rmse_va = [], {}

    def ghi(ten, p_va, p_te):
        a, b = chi_so(thuc_va, p_va), chi_so(thuc_te, p_te)
        rmse_va[ten] = a["RMSE"]
        ket_qua.append({"mo_hinh": ten, **b, "RMSE_kiem_dinh": a["RMSE"]})
        print(f"[{ten:24s}] kiểm tra: MAE={b['MAE']:.4f} RMSE={b['RMSE']:.4f} R2={b['R2']:.3f} MAPE={b['MAPE']:.1f}%")

    # mô hình cơ sở
    pp = lambda ts, ws: np.where(np.isnan(Y[ws, ts - 1]), C1[ws, moy[ts]], Y[ws, ts - 1])
    ghi(PERSIST, pp(tva, wva), pp(tte, wte))
    ghi(KHI_HAU, C1[wva, moy[tva]], C1[wte, moy[tte]])

    da_hoc = {}
    rf_tot, rf_rmse = None, np.inf
    for ten in danh_sach_mo_hinh():
        try:
            if ten == "Random Forest":      # thử vài cấu hình, chọn theo kiểm định
                for ts in ParameterGrid({"n_estimators": [100, 200], "max_depth": [6, 10], "min_samples_leaf": [5, 20]}):
                    m = tao_mo_hinh(ten, ts).fit(Xtr, Str, ytr)
                    r = np.sqrt(mean_squared_error(thuc_va, np.clip(C1[wva, moy[tva]] + m.predict(Xva, Sva), 0, 1)))
                    if r < rf_rmse: rf_tot, rf_rmse, mh = ts, r, m
            else:
                mh = tao_mo_hinh(ten).fit(Xtr, Str, ytr, Xva, Sva, yva)
            p_va = np.clip(C1[wva, moy[tva]] + mh.predict(Xva, Sva), 0, 1)
            p_te = np.clip(C1[wte, moy[tte]] + mh.predict(Xte, Ste), 0, 1)
            ghi(ten, p_va, p_te)
            da_hoc[ten] = True
        except Exception as e:           # một mô hình lỗi không làm hỏng cả quy trình
            print(f"! Bỏ qua {ten}: {e}")

    df_kq = pd.DataFrame(ket_qua)
    rmse_te_kh = df_kq.loc[df_kq["mo_hinh"] == KHI_HAU, "RMSE"].iloc[0]
    df_kq["so_voi_khi_hau"] = 1 - df_kq["RMSE"] / rmse_te_kh        # > 0: tốt hơn khí hậu
    df_kq.to_csv("ket_qua_so_sanh_mo_hinh.csv", index=False)

    ung_vien = {k: v for k, v in rmse_va.items() if k != PERSIST}
    tot = min(ung_vien, key=ung_vien.get)
    print(f"\nPhương pháp tốt nhất theo kiểm định: {tot}")
    if tot == KHI_HAU:
        print("! Không mô hình nào tốt hơn 'khí hậu theo tháng' trên tập kiểm định. "
              "Dự báo sẽ dùng khí hậu, và báo cáo cần nói rõ điều này.")

    # ---------- Giai đoạn 2: KIỂM CHỨNG bằng dữ liệu thật sau VAL_END ----------
    dong_bd = []
    if co_test:
        C2, w2 = khi_hau(Y, months, t_va)
        X2, S2, y2, _, _ = dung_tap(Y, C2, w2, moy, N_LAGS, t_va)
        mh2 = tao_mo_hinh(tot, rf_tot if tot == "Random Forest" else None).fit(X2, S2, y2)
        n_buoc = T - 1 - t_va
        pred = du_bao_de_quy(mh2, Y, C2, w2, moy, t_va + 1, n_buoc)
        kh = np.array([C2[:, moy[t_va + 1 + s]] for s in range(n_buoc)])
        tom_tat = []
        for s in range(n_buoc):
            y = Y[:, t_va + 1 + s]
            ok = ~np.isnan(y)
            if ok.sum() == 0: continue
            a, b = chi_so(y[ok], pred[s][ok]), chi_so(y[ok], kh[s][ok])
            tom_tat.append({"thang_du_bao": s + 1, "n": int(ok.sum()), "mae_mo_hinh": a["MAE"], "rmse_mo_hinh": a["RMSE"],
                            "mae_khi_hau": b["MAE"], "rmse_khi_hau": b["RMSE"]})
            y_, m_ = months[t_va + 1 + s]
            for i, w in enumerate(wards):
                dong_bd.append({"fullname": w, "nam": y_, "thang": m_, "tvdi_du_bao": round(float(pred[s][i]), 4),
                                "mo_hinh": tot, "loai": "kiem_chung"})
        pd.DataFrame(tom_tat).to_csv("kiem_chung_tom_tat.csv", index=False)
        print("\nKIỂM CHỨNG (huấn luyện đến %02d/%d, dự báo đệ quy rồi so với thật):" % (VAL_END[1], VAL_END[0]))
        print(pd.DataFrame(tom_tat).round(4).to_string(index=False))

    # ---------- Giai đoạn 3: dự báo tương lai ----------
    C3, w3 = khi_hau(Y, months, T - 1)
    X3, S3, y3, _, _ = dung_tap(Y, C3, w3, moy, N_LAGS, T - 1)
    mh3 = tao_mo_hinh(tot, rf_tot if tot == "Random Forest" else None).fit(X3, S3, y3)
    pred3 = du_bao_de_quy(mh3, Y, C3, w3, moy, T, HORIZON)
    y_, m_ = months[-1]
    for s in range(HORIZON):
        m_ += 1
        if m_ > 12: m_, y_ = 1, y_ + 1
        for i, w in enumerate(wards):
            dong_bd.append({"fullname": w, "nam": y_, "thang": m_, "tvdi_du_bao": round(float(pred3[s][i]), 4),
                            "mo_hinh": tot, "loai": "du_bao"})
    pd.DataFrame(dong_bd).to_csv("du_bao_phuong_xa.csv", index=False, encoding="utf-8")
    print(f"\nĐã ghi du_bao_phuong_xa.csv: {len(dong_bd):,} dòng ({n} phường/xã).")
    print("Khoảng giá trị dự báo tương lai: %.2f - %.2f (độ lệch chuẩn giữa phường/xã %.3f)" %
          (pred3.min(), pred3.max(), np.nanstd(pred3[0])))
    print("Giá trị này giữ NGUYÊN như mô hình tạo ra, không kéo giãn hay cộng trừ gì thêm.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else FILE_VAO)
