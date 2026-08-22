FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY config ./config

RUN pip install --no-cache-dir -e .

ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
