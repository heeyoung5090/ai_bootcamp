# Railway / Render 배포용 Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사 (service_account.json 제외 — 환경변수로 대체)
COPY main.py .
COPY admin.html .

# Railway가 PORT 환경변수를 자동으로 주입합니다
EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
