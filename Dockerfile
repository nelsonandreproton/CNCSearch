FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY cncsearch/ ./cncsearch/
COPY templates/ ./templates/
COPY static/ ./static/

ENV DATABASE_PATH=/data/cncsearch.db
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "cncsearch.web.app:app", "--host", "0.0.0.0", "--port", "8080"]
