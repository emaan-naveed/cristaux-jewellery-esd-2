# Cristaux Jewellery — Observability Assignment 1

An enterprise luxury jewellery e-commerce application built with **FastAPI**, **Prometheus**, **Grafana**, **Node Exporter**, **Filebeat**, **Elasticsearch**, and **Kibana**.

---

##  Architecture & Services Summary

| Service | URL / Port | Description & Purpose |
|---|---|---|
| **Cristaux Jewellery App & Storefront** | http://localhost:8000 | Interactive Haute Joaillerie E-commerce Storefront & REST APIs |
| **Prometheus Metrics Target** | http://localhost:8000/metrics | Scrape endpoint exposing all 4 Prometheus metric types |
| **Prometheus Server** | http://localhost:9090 | Telemetry time-series database scraping metrics every 15s |
| **Grafana Dashboards** | http://localhost:3000 | Pre-provisioned visual charts (Login: `admin` / `admin`) |
| **Node Exporter** | http://localhost:9100/metrics | System metrics agent (CPU, memory, disk, network) |
| **Elasticsearch** | http://localhost:9200 | Distributed document store indexing structured JSON logs |
| **Kibana** | http://localhost:5601 | Log search and analytics dashboard |
| **Filebeat** | Background | Log shipper harvesting Docker JSON logs to Elasticsearch |

---

## Prerequisites

- **Docker Desktop** (with Compose v2)
- At least **4 GB Memory** allocated to Docker (required for Elasticsearch).

---

## How to Start, Test & Run

### 1. Launch Containers
```bash
docker compose up -d --build
```

### 2. Simulate User Traffic
Run the simulation script to place orders and generate metrics/logs:
```bash
py -3 seed_traffic.py
```

### 3. Verification & UI Inspection
- **Interactive Storefront**: Open [http://localhost:8000](http://localhost:8000) and click **"Order Now"** on luxury jewellery items.
- **Prometheus Scrape Endpoint**: Verify metrics at [http://localhost:8000/metrics](http://localhost:8000/metrics).
- **Grafana Dashboard**: Open [http://localhost:3000](http://localhost:3000) (admin / admin) $\rightarrow$ Dashboards $\rightarrow$ **Jewellery Store Observability Dashboard**.
- **Kibana Log Search**: Open [http://localhost:5601](http://localhost:5601) $\rightarrow$ Create Data View (`app-logs-*`) $\rightarrow$ Analytics $\rightarrow$ Discover.

---

## Part E Experiments

### 1. Latency Anomaly Test (Fault Injection)
- **Trigger Anomaly (500ms artificial delay)**:
  ```bash
  curl -X POST http://localhost:8000/admin/fault -H "Content-Type: application/json" -d "{\"delay_ms\": 500}"
  ```
- **Observe**: Notice the p95 latency spike in Grafana and slow duration logs in Kibana.
- **Reset Anomaly**:
  ```bash
  curl -X POST http://localhost:8000/admin/fault -H "Content-Type: application/json" -d "{\"delay_ms\": 0}"
  ```

### 2. Cardinality Explosion Test
- **Execute Test**:
  ```bash
  curl http://localhost:8000/admin/cardinality-test
  ```
- **Observe**: Run `count(demo_requests_total)` in Prometheus graph to witness time-series proliferation.

---

---

## Part A: REST Principles & Reliability Extension

### 1. Interactive OpenAPI Specification & Swagger UI
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc UI**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Raw OpenAPI Spec**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json) (or inspect [`openapi.json`](./openapi.json))
- **Export Schema Command**:
  ```bash
  py export_openapi.py
  ```

### 2. Run Automated Test Suite (Validation, Idempotency, Rate Limiting)
Runs comprehensive tests for valid request (`201 Created`), invalid input (`400/422` with consistent error schema), repeated request (`Idempotency-Key` replay), and rate limiting (`429 Too Many Requests` with `Retry-After`):
```bash
py test_api.py
```

### 3. Run Resilient Python Caller Service
Demonstrates client-side timeouts, exponential backoff retries on safe operations, and 3-state circuit breaker (`CLOSED` $\rightarrow$ `OPEN` $\rightarrow$ `HALF-OPEN` $\rightarrow$ `CLOSED`):
```bash
py caller.py
```

---

##  Cleanup & Teardown

Stop containers while keeping data:
```bash
docker compose down
```

Remove containers, networks, and all stored data volumes:
```bash
docker compose down -v
```

