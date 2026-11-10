import json
import logging
import os
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from typing import Any, cast

from fastapi import FastAPI, Request
from sqlalchemy import DateTime, Float, Integer, String, create_engine, func, insert, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import QueuePool


logger = logging.getLogger("payment_api")
logging.basicConfig(level=logging.INFO, format="%(message)s")


class Base(DeclarativeBase):
    pass


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class PaymentSettings:
    database_url: str
    release: str = "3.8.1"
    pool_size: int = 5
    max_overflow: int = 0
    pool_timeout: int = 2
    hold_seconds: float = 0.3

    @classmethod
    def from_environment(cls) -> "PaymentSettings":
        return cls(
            database_url=os.getenv(
                "PAYMENT_DATABASE_URL",
                "postgresql+psycopg://payments:payments@127.0.0.1:5432/payments",
            ),
            release=os.getenv("PAYMENT_API_VERSION", "3.8.1"),
            pool_size=int(os.getenv("PAYMENT_DB_POOL_SIZE", "5")),
            max_overflow=int(os.getenv("PAYMENT_DB_MAX_OVERFLOW", "0")),
            pool_timeout=int(os.getenv("PAYMENT_DB_POOL_TIMEOUT", "2")),
            hold_seconds=float(os.getenv("PAYMENT_DB_HOLD_SECONDS", "0.3")),
        )

    def validate(self) -> None:
        if make_url(self.database_url).get_backend_name() != "postgresql":
            raise ValueError("The Payment API sandbox requires PostgreSQL; SQLite is not supported.")
        if self.release not in {"previous", "3.8.1"}:
            raise ValueError("Unsupported Payment API release.")
        if not 1 <= self.pool_size <= 100 or not 0 <= self.max_overflow <= 100:
            raise ValueError("Invalid database pool configuration.")
        if not 1 <= self.pool_timeout <= 60 or not 0.0 <= self.hold_seconds <= 10.0:
            raise ValueError("Invalid database operation timing configuration.")


class RequestMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._requests = 0
        self._errors = 0
        self._latencies_ms: deque[float] = deque(maxlen=10_000)

    def record(self, status_code: int, elapsed_ms: float) -> None:
        with self._lock:
            self._requests += 1
            self._errors += int(status_code >= 500)
            self._latencies_ms.append(elapsed_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            latencies = sorted(self._latencies_ms)
            count = len(latencies)
            p95_index = max(0, int(count * 0.95 + 0.999999) - 1)
            return {
                "request_count": self._requests,
                "error_count": self._errors,
                "latency_ms": {
                    "count": count,
                    "mean": round(sum(latencies) / count, 3) if count else 0,
                    "p95": round(latencies[p95_index], 3) if count else 0,
                    "max": round(latencies[-1], 3) if count else 0,
                },
            }


def create_app(
    settings: PaymentSettings | None = None,
    engine: Engine | None = None,
    metrics: RequestMetrics | None = None,
    initialize_database: bool = True,
) -> FastAPI:
    config = settings or PaymentSettings.from_environment()
    config.validate()
    database = engine or create_engine(
        config.database_url,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_timeout=config.pool_timeout,
        pool_pre_ping=True,
    )
    request_metrics = metrics or RequestMetrics()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if initialize_database:
            Base.metadata.create_all(database)
            with database.begin() as connection:
                if connection.scalar(select(func.count()).select_from(Payment)) == 0:
                    connection.execute(
                        insert(Payment),
                        [
                            {"amount": 42.50, "currency": "USD", "status": "succeeded", "created_at": datetime(2026, 10, 1, tzinfo=timezone.utc)},
                            {"amount": 18.25, "currency": "USD", "status": "succeeded", "created_at": datetime(2026, 10, 2, tzinfo=timezone.utc)},
                            {"amount": 73.00, "currency": "USD", "status": "refunded", "created_at": datetime(2026, 10, 3, tzinfo=timezone.utc)},
                            {"amount": 110.00, "currency": "USD", "status": "succeeded", "created_at": datetime(2026, 10, 4, tzinfo=timezone.utc)},
                            {"amount": 9.99, "currency": "USD", "status": "failed", "created_at": datetime(2026, 10, 5, tzinfo=timezone.utc)},
                        ],
                    )
        yield

    application = FastAPI(title="Payment API Sandbox", version=config.release, lifespan=lifespan)
    application.state.settings = config
    application.state.engine = database
    application.state.metrics = request_metrics

    @application.middleware("http")
    async def record_request(request: Request, call_next):
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as error:
            logger.error(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "severity": "ERROR",
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": 500,
                        "exception_type": type(error).__name__,
                        "error": str(error),
                    },
                    sort_keys=True,
                )
            )
            raise
        finally:
            elapsed_ms = (perf_counter() - started) * 1000
            request_metrics.record(status_code, elapsed_ms)
            if status_code < 500:
                logger.info(
                    json.dumps(
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "severity": "INFO",
                            "method": request.method,
                            "path": request.url.path,
                            "status_code": status_code,
                            "latency_ms": round(elapsed_ms, 3),
                        },
                        sort_keys=True,
                    )
                )

    @application.get("/health")
    def health() -> dict[str, Any]:
        with database.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "release": config.release,
            "pool_size": config.pool_size,
            "max_overflow": config.max_overflow,
            "pool_timeout": config.pool_timeout,
        }

    @application.get("/control/config")
    def active_config() -> dict[str, Any]:
        return {
            "service": "payment-api",
            "release": config.release,
            "pool_size": config.pool_size,
            "max_overflow": config.max_overflow,
            "pool_timeout": config.pool_timeout,
            "hold_seconds": config.hold_seconds,
        }

    @application.get("/metrics")
    def metrics_snapshot() -> dict[str, Any]:
        pool = cast(QueuePool, database.pool)
        return {
            **request_metrics.snapshot(),
            "connection_pool": {
                "size": pool.size(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
                "max_overflow": config.max_overflow,
                "timeout_seconds": config.pool_timeout,
            },
        }

    if config.release == "3.8.1":

        @application.get("/payments/summary")
        def payment_summary() -> dict[str, Any]:
            with database.connect() as connection:
                connection.execute(
                    text("SELECT pg_sleep(:hold_seconds)"),
                    {"hold_seconds": config.hold_seconds},
                )
                total_count, successful_count, refunded_count, total_amount = connection.execute(
                    select(
                        func.count(Payment.id),
                        func.count(Payment.id).filter(Payment.status == "succeeded"),
                        func.count(Payment.id).filter(Payment.status == "refunded"),
                        func.coalesce(func.sum(Payment.amount).filter(Payment.status == "succeeded"), 0.0),
                    )
                ).one()
            return {
                "release": config.release,
                "currency": "USD",
                "payment_count": total_count,
                "successful_count": successful_count,
                "refunded_count": refunded_count,
                "successful_amount": round(float(total_amount), 2),
            }

    return application


app = create_app()