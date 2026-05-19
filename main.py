"""
AI 부트캠프 지원 현황 API — FastAPI
구글시트 인증: Google Service Account
"""

import os
import re
import csv
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import gspread
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from google.oauth2.service_account import Credentials

load_dotenv()

# ============================================================
# [필수] .env 파일 또는 Railway 환경변수로 설정
# ============================================================
SHEET_ID = os.environ.get("SHEET_ID", "YOUR_GOOGLE_SHEET_ID")

# Railway / Render 배포 환경 감지 (로그 파일 저장 여부 결정)
IS_SERVER = bool(
    os.environ.get("RAILWAY_ENVIRONMENT")
    or os.environ.get("RENDER")
    or os.environ.get("FLY_APP_NAME")
)

# ============================================================
# 시트 열 순서 (구글시트 컬럼 순서와 동일)
# ============================================================
COL_NAMES = [
    "timestamp",         # 타임스탬프
    "department",        # 학부(과)
    "student_id",        # 학번
    "grade",             # 학년
    "name",              # 이름
    "phone",             # 휴대폰번호
    "level",             # 신청영역
    "basic_courses",     # '초급' 과목 신청
    "advanced_courses",  # '중급' 과목 신청
    "a1_credits",        # A1 인정교과목
    "a2_credits",        # A2 인정교과목
    "a3_credits",        # A3 인정교과목
    "b1_credits",        # B1 인정교과목
    "b2_credits",        # B2 인정교과목
]

# ============================================================
# Google Sheets 인증
# GOOGLE_CREDENTIALS 환경변수: service_account.json 내용 전체
# (Railway 등 배포 환경에서는 환경변수, 로컬에서는 파일 사용)
# ============================================================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

def get_gspread_client() -> gspread.Client:
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if creds_json:
        # 배포 환경: 환경변수에서 JSON 파싱
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        # 로컬 환경: 파일에서 읽기
        key_file = Path("service_account.json")
        if not key_file.exists():
            raise FileNotFoundError(
                "service_account.json 파일이 없습니다. "
                "Google Cloud Console에서 서비스 계정 키를 다운로드하세요."
            )
        creds = Credentials.from_service_account_file(str(key_file), scopes=SCOPES)
    return gspread.authorize(creds)


# ============================================================
# 유틸 함수
# ============================================================

def parse_korean_ts(ts: str) -> str:
    """한국어 타임스탬프 → 'YYYY-MM-DD HH:MM:SS'"""
    if not ts or not ts.strip():
        return ""
    is_pm = "오후" in ts
    is_am = "오전" in ts
    ts_clean = ts.replace("오전", "").replace("오후", "")
    nums = re.findall(r"\d+", ts_clean)
    if len(nums) < 6:
        return ""
    year, month, day, hour, minute, second = (int(n) for n in nums[:6])
    if is_pm and hour < 12:
        hour += 12
    if is_am and hour == 12:
        hour = 0
    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"


def extract_codes(text: str) -> list[str]:
    """과목 코드 추출 (A1~A3, B1~B3)"""
    if not text:
        return []
    return list(set(re.findall(r"[AB][1-3]", text)))


def safe(val) -> str:
    """None / 'nan' 방어 처리"""
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s.lower() in ("none", "nan", "n/a") else s


# ============================================================
# FastAPI 앱
# ============================================================
app = FastAPI(title="AI 부트캠프 지원 현황 API", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ── GET /  →  admin.html 서빙 ─────────────────────────────
@app.get("/", response_class=HTMLResponse)
def serve_admin():
    html_path = Path("admin.html")
    if not html_path.exists():
        return HTMLResponse(
            "<h1>admin.html 파일이 없습니다.</h1>"
            "<p>main.py와 같은 폴더에 admin.html을 넣어주세요.</p>",
            status_code=404,
        )
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ── GET /data  →  지원자 데이터 + 통계 ───────────────────
@app.get("/data")
def get_data():
    try:
        client = get_gspread_client()
        sheet  = client.open_by_key(SHEET_ID).sheet1
        rows   = sheet.get_all_values()  # 헤더 포함 전체 행

    except Exception as e:
        import traceback
        traceback.print_exc()   # 터미널에 전체 오류 스택 출력
        return JSONResponse(
            {"success": False, "error": f"구글시트 읽기 실패: {e}"},
            status_code=500,
        )

    # 헤더 행 제외 (rows[0] = 헤더)
    data_rows = rows[1:] if len(rows) > 1 else []

    records = []
    for row in data_rows:
        # 열 수 부족 시 빈 문자열로 채움
        while len(row) < len(COL_NAMES):
            row.append("")

        r = dict(zip(COL_NAMES, row))
        ts_str   = parse_korean_ts(r["timestamp"])
        date_str = ts_str[:10] if len(ts_str) >= 10 else ""

        records.append(
            {
                "timestamp":        ts_str,
                "date":             date_str,
                "department":       safe(r["department"]),
                "student_id":       safe(r["student_id"]),
                "grade":            safe(r["grade"]),
                "name":             safe(r["name"]),
                "phone":            safe(r["phone"]),
                "level":            safe(r["level"]),
                "basic_courses":    safe(r["basic_courses"]),
                "advanced_courses": safe(r["advanced_courses"]),
                "a1_credits":       safe(r["a1_credits"]),
                "a2_credits":       safe(r["a2_credits"]),
                "a3_credits":       safe(r["a3_credits"]),
                "b1_credits":       safe(r["b1_credits"]),
                "b2_credits":       safe(r["b2_credits"]),
            }
        )

    today    = date.today().strftime("%Y-%m-%d")
    week_ago = (date.today() - timedelta(days=6)).strftime("%Y-%m-%d")

    today_count = sum(1 for r in records if r["date"] == today)
    week_count  = sum(1 for r in records if week_ago <= r["date"] <= today)
    basic_count = sum(1 for r in records if r["level"] == "초급")
    adv_count   = sum(1 for r in records if r["level"] == "중급")

    # 과목 코드별 집계
    all_codes: list[str] = []
    for r in records:
        all_codes.extend(extract_codes(r["basic_courses"]))
        all_codes.extend(extract_codes(r["advanced_courses"]))
    course_counts = dict(Counter(all_codes))

    # 학과별 집계
    dept_counts = dict(
        Counter(r["department"] for r in records if r["department"])
    )

    # 일별 집계
    daily_counts = dict(
        Counter(r["date"] for r in records if r["date"])
    )

    return {
        "success":       True,
        "updated_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total":         len(records),
        "today":         today_count,
        "week":          week_count,
        "basic":         basic_count,
        "advanced":      adv_count,
        "course_counts": course_counts,
        "dept_counts":   dept_counts,
        "daily_counts":  daily_counts,
        "records":       records,
    }


# ── GET /health ───────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


# ── POST /log  →  활동 로그 저장 ─────────────────────────
@app.post("/log")
async def save_log(request: Request):
    try:
        body = await request.json()
        msg  = body.get("message", "").strip()
        if not msg:
            return {"success": False, "error": "메시지 없음"}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 콘솔 출력 (Railway 대시보드 로그에서 확인 가능)
        print(f"[LOG] {now} | {msg}")

        # 로컬 실행 시에만 CSV 파일 저장
        if not IS_SERVER:
            log_path   = Path("activity_log.csv")
            is_new     = not log_path.exists()
            with open(log_path, "a", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                if is_new:
                    writer.writerow(["datetime", "message"])
                writer.writerow([now, msg])

        return {"success": True}

    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ============================================================
# 로컬 실행 진입점
# python main.py
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"서버 시작: http://localhost:{port}")
    print("관리자 페이지: http://localhost:{port}/".format(port=port))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)