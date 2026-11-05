FROM python:3.12-slim
WORKDIR /app
COPY python/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY python /app/python
COPY knowledge /app/knowledge
COPY web /app/web
ENV PYTHONPATH=/app/python PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
