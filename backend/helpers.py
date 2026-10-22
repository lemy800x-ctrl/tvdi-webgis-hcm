"""Các hàm thuần (không cần database/web) để dễ kiểm thử."""
from typing import List, Optional, Tuple

# 5 mức khô hạn theo ngưỡng TVDI thường dùng trong các nghiên cứu (0-1).
# Có thể chỉnh lại cho khớp với mục 3 của đề cương.
CLASSES = [
    (0.2, "Rất ẩm"),
    (0.4, "Ẩm"),
    (0.6, "Trung bình"),
    (0.8, "Khô"),
    (float("inf"), "Rất khô"),
]


def classify(v: Optional[float]) -> Optional[int]:
    """Trả về chỉ số mức khô hạn 0..4 (None nếu không có dữ liệu)."""
    if v is None:
        return None
    for i, (upper, _) in enumerate(CLASSES):
        if v < upper:
            return i
    return len(CLASSES) - 1


def class_label(level: Optional[int]) -> Optional[str]:
    return None if level is None else CLASSES[level][1]


def add_months(nam: int, thang: int, k: int) -> Tuple[int, int]:
    idx = nam * 12 + (thang - 1) + k
    return idx // 12, idx % 12 + 1


def recursive_forecast(model, scaler, history: List[float], horizon: int,
                       n_lags: int = 6) -> List[float]:
    """
    Dự báo đệ quy: dùng n_lags giá trị gần nhất để dự báo tháng kế tiếp,
    rồi đưa chính giá trị vừa dự báo vào làm đầu vào cho tháng sau nữa.
    """
    if len(history) < n_lags:
        raise ValueError(f"Cần ít nhất {n_lags} tháng dữ liệu, hiện chỉ có {len(history)}.")
    window = list(history[-n_lags:])
    out = []
    for _ in range(horizon):
        x = scaler.transform([window]) if scaler is not None else [window]
        pred = float(model.predict(x)[0])
        pred = min(max(pred, 0.0), 1.0)  # TVDI hiển thị trong khoảng 0-1
        out.append(pred)
        window = window[1:] + [pred]
    return out
