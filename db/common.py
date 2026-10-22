"""Kết nối PostgreSQL dùng chung cho các script nạp dữ liệu."""
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

# Đọc file .env ở thư mục gốc dự án (tvdi_web/.env)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def get_conn():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit(
            "Chưa có DATABASE_URL. Copy file .env.example thành .env "
            "rồi điền thông tin kết nối PostgreSQL."
        )
    return psycopg2.connect(url)
