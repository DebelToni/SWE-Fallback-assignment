# SWE-Fallback-assignment

Python service с fallback между два външни backend-а, Prometheus метрики, JSON логове и Dockerized Prometheus.

## Endpoints

- `GET /todos` - връща todos от primary backend, а при грешка минава към fallback backend
- `GET /metrics` - Prometheus метрики
- `GET /health` - health check

По подразбиране приблизително 1 от 10 заявки към `/todos` симулира отказ на primary backend, за да се генерират fallback логове и Prometheus данни.

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Docker run

```bash
docker compose up --build
```

Ако искате да смените честотата:

```bash
FALLBACK_SAMPLE_RATE=0.2 docker compose up --build
```

За да форсирате fallback и да видите брояча да се увеличава:

```bash
PRIMARY_TODOS_URL=http://127.0.0.1:1/todos docker compose up --build
```

След стартиране:

- App: `http://localhost:8000/todos`
- Metrics: `http://localhost:8000/metrics`
- Prometheus: `http://localhost:9090`

## Как да се види fallback-а

Счупете primary backend URL-а за текущата сесия и извикайте `/todos`:

```bash
PRIMARY_TODOS_URL=http://does-not-exist uvicorn app.main:app --host 0.0.0.0 --port 8000
```

След това отворете в Prometheus:

```text
todos_fallback_total
```

При всеки fallback приложението пише JSON log със събитие `fallback_triggered`.

## Screenshot

Готов screenshot на Prometheus визуализацията:

- `docs/prometheus-counter.png`
