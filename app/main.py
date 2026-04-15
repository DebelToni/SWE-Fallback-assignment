import json
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest


PRIMARY_BACKEND_NAME = "jsonplaceholder"
PRIMARY_BACKEND_URL = os.getenv(
    "PRIMARY_TODOS_URL", "https://jsonplaceholder.typicode.com/todos"
)
FALLBACK_BACKEND_NAME = "dummyjson"
FALLBACK_BACKEND_URL = os.getenv("SECONDARY_TODOS_URL", "https://dummyjson.com/todos")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "5"))
FALLBACK_SAMPLE_RATE = float(os.getenv("FALLBACK_SAMPLE_RATE", "0.1"))

FALLBACK_COUNTER = Counter(
    "todos_fallback_total",
    "Number of times the fallback backend served the todos response.",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        return json.dumps(payload, ensure_ascii=True)


logger = logging.getLogger("fallback-service")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

app = FastAPI(title="Fallback Service", version="1.0.0")


class SimulatedPrimaryFailure(Exception):
    pass


def normalize_todos(source: str, payload: Any) -> list[dict[str, Any]]:
    if source == PRIMARY_BACKEND_NAME:
        raw_todos = payload
    elif source == FALLBACK_BACKEND_NAME:
        raw_todos = payload.get("todos", [])
    else:
        raise ValueError(f"Unsupported backend source: {source}")

    normalized: list[dict[str, Any]] = []
    for item in raw_todos:
        normalized.append(
            {
                "id": item.get("id"),
                "userId": item.get("userId"),
                "title": item.get("title") or item.get("todo"),
                "completed": bool(item.get("completed", False)),
            }
        )
    return normalized


async def fetch_todos(source: str, url: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(url)
        response.raise_for_status()
        return normalize_todos(source, response.json())


def should_simulate_primary_failure() -> bool:
    return FALLBACK_SAMPLE_RATE > 0 and random.random() < FALLBACK_SAMPLE_RATE


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/todos")
async def get_todos() -> dict[str, Any]:
    try:
        if should_simulate_primary_failure():
            raise SimulatedPrimaryFailure(
                f"Primary backend skipped by sampler at rate {FALLBACK_SAMPLE_RATE:.2f}"
            )
        todos = await fetch_todos(PRIMARY_BACKEND_NAME, PRIMARY_BACKEND_URL)
        return {
            "source": PRIMARY_BACKEND_NAME,
            "fallbackUsed": False,
            "count": len(todos),
            "todos": todos,
        }
    except (httpx.HTTPError, ValueError, SimulatedPrimaryFailure) as primary_error:
        FALLBACK_COUNTER.inc()
        logger.warning(
            "fallback_triggered",
            extra={
                "extra_fields": {
                    "event": "fallback_triggered",
                    "primaryBackend": PRIMARY_BACKEND_NAME,
                    "primaryUrl": PRIMARY_BACKEND_URL,
                    "fallbackBackend": FALLBACK_BACKEND_NAME,
                    "fallbackUrl": FALLBACK_BACKEND_URL,
                    "error": str(primary_error),
                    "errorType": type(primary_error).__name__,
                    "fallbackSampleRate": FALLBACK_SAMPLE_RATE,
                }
            },
        )
        try:
            todos = await fetch_todos(FALLBACK_BACKEND_NAME, FALLBACK_BACKEND_URL)
        except (httpx.HTTPError, ValueError) as fallback_error:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Both backends failed.",
                    "primaryError": str(primary_error),
                    "fallbackError": str(fallback_error),
                },
            ) from fallback_error

        return {
            "source": FALLBACK_BACKEND_NAME,
            "fallbackUsed": True,
            "count": len(todos),
            "todos": todos,
        }


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
