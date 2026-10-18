FROM python:3.12-slim

WORKDIR /app

# Unbuffered output matters: without it Python holds log lines in a buffer
# and Docker (and therefore Filebeat) sees them late or not at all.
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --default-timeout=100 --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
