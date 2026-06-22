FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/pipeline/src

WORKDIR /app

COPY api/requirements.txt api/requirements.txt
COPY pipeline/requirements.txt pipeline/requirements.txt

RUN pip install --no-cache-dir -r api/requirements.txt -r pipeline/requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
