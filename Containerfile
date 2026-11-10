FROM python:3.12-slim

ARG PAYMENT_API_VERSION=3.8.1
ENV PAYMENT_API_VERSION=${PAYMENT_API_VERSION}
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY payment_api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY payment_api /app/payment_api

EXPOSE 8000
CMD ["uvicorn", "payment_api.app:app", "--host", "0.0.0.0", "--port", "8000"]