# Cristaux Jewellery — Assignment 2: HTTP APIs, gRPC, and Metrics

An enterprise luxury jewellery e-commerce application extending the **Assignment 1** observability project. Assignment 2 adds **Part A** (REST principles + reliability practices for the HTTP API) and **Part B** (a standalone gRPC service for order lifecycle operations).

Built with **FastAPI**, **gRPC**, **SQLite**, **Prometheus**, **Grafana**, **Filebeat**, **Elasticsearch**, and **Kibana**.

---

## Architecture & Services Summary

| Service | URL / Port | Description & Purpose |
|---|---|---|
| **Cristaux Jewellery App & Storefront** | http://localhost:8000 | Interactive Haute Joaillerie E-commerce Storefront & REST APIs (Part A) |
| **gRPC Order Service (Part B)** | grpc://localhost:50051 · http://localhost:50052/metrics | Standalone gRPC `OrderService` (`CancelOrder` / `GetOrder`) sharing the same SQLite source of truth & business rules as the REST API; `/metrics` for Prometheus (Part C) |
| **Prometheus Metrics Target** | http://localhost:8000/metrics | Scrape endpoint exposing all 4 Prometheus metric types (Assignment 1) |
| **Prometheus Server** | http://localhost:9090 | Telemetry time-series database scraping metrics every 15s |
| **Grafana Dashboards** | http://localhost:3000 | Pre-provisioned visual charts (Login: `admin` / `admin`) |
| **Kibana Log Search** | http://localhost:5601 | Structured log search over `app-logs-*` (HTTP + gRPC services) |

---

## Prerequisites

- **Docker Desktop** (with Compose v2)
- At least **4 GB Memory** allocated to Docker (required for Elasticsearch).
- Python 3.12+ with `fastapi`, `grpcio`, `grpcio-tools`, `requests`, `prometheus_client` for standalone runs.

---

## Quick Start

```bash
# 1. Launch both services + the Assignment 1 observability stack
docker compose up -d --build
# REST API     -> http://localhost:8000
# gRPC service -> grpc://localhost:50051

# 2. Simulate user traffic (places orders, generates metrics/logs)
py -3 seed_traffic.py

# 3. Interactive storefront: open http://localhost:8000 and click "Order Now"
```

Standalone (no Docker):

```bash
# Terminal 1 — REST API
py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# Terminal 2 — gRPC server
py -3 grpc_server.py
```

---

## Part A: Improve the HTTP API (40 marks)

### 1. REST Principles — The Six Constraints

| # | Constraint | Plain-language meaning | Example in this API (or not demonstrated) |
|---|---|---|---|
| 1 | **Client–Server** | UI and data storage live in separate components so each can evolve independently. | The browser storefront (`GET /`) is pure HTML/JS that calls the REST API (`/api/v1/...`). The server owns the DB and business rules. |
| 2 | **Stateless** | Each request contains everything it needs; the server stores no client session between requests. | Each order request is self-contained via the `Idempotency-Key` header — no server session. *Not fully demonstrated:* the single-instance rate limiter keeps a per-IP window in memory. |
| 3 | **Cacheable** | Responses must declare whether they may be cached so clients/proxies can reuse them. | *Not strongly demonstrated.* `GET /api/v1/products` and `GET /api/v1/orders` have safe/idempotent semantics but no explicit `Cache-Control` headers are set. |
| 4 | **Uniform Interface** | A consistent way to address and manipulate resources: standard methods, resource paths, consistent representations. | Uniform JSON envelope `{...}` for success and `{"error":{code,message,details,timestamp}}` for errors; correct methods (`GET`/`POST`/`PATCH`/`DELETE`); `Location` header on creation. |
| 5 | **Layered System** | A client cannot tell whether it is talking to the end server or an intermediary along the way. | The app runs behind Docker; the storefront calls `/api/v1/...` regardless of whether a proxy sits in front. Part B's gRPC service is another layer sharing the same DB. |
| 6 | **Code on Demand** *(optional)* | The server may ship executable code (e.g. JS) to extend the client at runtime. | The `GET /` storefront returns inline JavaScript that runs in the browser and calls the API. Marked optional per the brief. |

### 2. REST Practices Applied (Endpoint Review)

All application endpoints (excluding `/health` and `/metrics`) were reviewed for clear paths, appropriate methods, input validation, and meaningful status codes with a consistent error format.

| Method | Path | Purpose | Status codes |
|---|---|---|---|
| GET | `/api/v1/products` | List catalogue (optional `?category=` filter) | 200 |
| GET | `/api/v1/products/{product_id}` | Get one product | 200, 404 |
| GET | `/api/v1/cart/{cart_id}` | View cart | 200, 404 |
| POST | `/api/v1/cart/items` | Add item to cart | 200, 404 (unknown product) |
| DELETE | `/api/v1/cart/{cart_id}` | Clear cart | 200 |
| GET | `/api/v1/orders` | List all orders | 200 |
| GET | `/api/v1/orders/{order_id}` | Get one order | 200, 404 |
| POST | `/api/v1/orders` | Place an order (idempotent, rate-limited) | 201, 400, 404, 422, 429 |
| PATCH | `/api/v1/orders/{order_id}` | Update order status (cancel/fulfill) | 200, 404, 409 |

- **Input validation:** Pydantic models (`AddToCartRequest`, `OrderRequest`, `UpdateOrderStatusRequest`) enforce field lengths, ranges, and email format; failures return `422 VALIDATION_ERROR` with a consistent envelope.
- **Consistent error format:** every failure returns `{"error":{"code","message","details","timestamp"}}` via central exception handlers (`validation_exception_handler`, `http_exception_handler`).

### 3. OpenAPI Specification

The OpenAPI Specification is a machine-readable contract (JSON/YAML) that describes an API's routes, request/response schemas, status codes, and error shapes. Tools use it to generate interactive docs and client SDKs, and to drive automated testing. In this project FastAPI auto-generates the spec at `/openapi.json`, served through Swagger UI and ReDoc, and `export_openapi.py` writes it to disk.

- **Swagger UI (try it live):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Raw spec:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json) (or [`openapi.json`](./openapi.json))
- **Export to disk:**
  ```bash
  py -3 export_openapi.py
  ```

**Testing an endpoint via the spec:** open Swagger UI → expand `POST /api/v1/orders` → "Try it out" → paste a body like `{"cart_id":"sw-cart-1","customer_email":"u@cristaux.com"}` and an `Idempotency-Key` header → "Execute". Swagger sends the request, shows the `201 Created` response and the `Location` / `Idempotent-Replay` headers, validating that the live API matches the spec.

### 4. Idempotency (Safe Repeats)

`POST /api/v1/orders` is the operation that may be retried (network timeouts, double-clicks). Placing an order is **not** naturally safe — repeating it would create a duplicate paid order. To make retries safe, the endpoint accepts an `Idempotency-Key` request header:

1. On the first call the server stores the created order under the key and returns `201` with `Idempotent-Replay: false`.
2. On any repeat with the **same** key it returns the **cached** order (`201`, `Idempotent-Replay: true`) without creating a second record.

Verified by `test_api.py` (Test 3): two identical requests with the same key return the **same** `order_id`, and the database contains exactly one order:

```
--- TEST 3: Idempotency (Safe Repeats) ---
1st Response Status: 201, Order ID: ord-3793fe8c, Replay Header: false
2nd Response Status: 201, Order ID: ord-3793fe8c, Replay Header: true
Verified database: exactly 1 order exists for ID ord-3793fe8c (NO duplicates created).
>>> TEST 3 PASSED: Repeated request safely handled via Idempotency-Key.
```

### 5. Rate Limiting

Rate limiting is applied to **one endpoint**: `POST /api/v1/orders`. A single-instance sliding-window limiter (`InMemoryRateLimiter`) tracks the last 10 seconds of calls per client IP.

- **Limit:** 5 order requests per 10-second rolling window.
- **Who shares it:** every call from the **same client IP** shares the counter (single-instance — sufficient for one container).
- **When calls are allowed again:** after the oldest request in the window ages out (≤ 10s). The `Retry-After` header tells the client exactly how long to wait.
- **Over-limit response:** `429 Too Many Requests` with `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, and the consistent error body `RATE_LIMIT_EXCEEDED`.

Verified by `test_api.py` (Test 4) — burst of 6 requests:

```
Request #1: Status=201, X-RateLimit-Remaining=4
Request #2: Status=201, X-RateLimit-Remaining=3
Request #3: Status=201, X-RateLimit-Remaining=2
Request #4: Status=201, X-RateLimit-Remaining=1
Request #5: Status=201, X-RateLimit-Remaining=0
Request #6: Status=429, X-RateLimit-Remaining=0, Retry-After=10
429 Response: code=RATE_LIMIT_EXCEEDED, "Maximum 5 orders per 10 seconds allowed. Please retry after 10 seconds."
>>> TEST 4 PASSED: Rate limit accepted 5 requests, rejected 6th with 429 & Retry-After header.
```

### 6. Before / After — One User Task (Place an Order)

| Old endpoint / behaviour | Problem | Change | Reason |
|---|---|---|---|
| `POST /orders` → `200 OK`, no `Location` | Wrong success code for a newly created resource; client cannot address the new order; no versioning | `POST /api/v1/orders` → `201 Created` + `Location: /api/v1/orders/{id}` on a versioned path | `201` + `Location` is the REST-correct response for resource creation; versioning allows future evolution without breaking clients |
| No idempotency — a retry creates a duplicate paid order | Timeouts / double-clicks double-charge customers | `Idempotency-Key` header; replays return the cached order with `Idempotent-Replay: true` | `POST` is not safe; the idempotency key makes retries safe with no duplicate effects |
| No rate limiting — any client can burst unlimited orders | Accidental floods or abuse can exhaust the service | 5 orders / 10s per client IP; the 6th returns `429` + `Retry-After` | Protects the service from abuse and accidental floods |
| Ad-hoc error bodies | Callers cannot reliably parse failures | Uniform `{"error":{code,message,details,timestamp}}` for all errors | Predictable error contract for every caller |

### 7. Other Endpoints Changed or Left Alone

**Changed (versioned + REST-aligned; legacy aliases kept for backward compatibility):**
- `GET /products` → `GET /api/v1/products`; new `GET /api/v1/products/{product_id}`
- `POST /cart` → `POST /api/v1/cart/items`; new `GET /api/v1/cart/{cart_id}` and `DELETE /api/v1/cart/{cart_id}`
- `GET /api/orders` → `GET /api/v1/orders`; new `GET /api/v1/orders/{order_id}`
- `POST /orders/{id}/cancel` and `POST /orders/{id}/fulfill` (RPC-style, verb in URL) → `PATCH /api/v1/orders/{id}` with body `{"status":"cancelled"\|"fulfilled","reason":...}` — `PATCH` is the correct method for partial resource state changes, and the path names the resource, not the action.

**Left unchanged (per the brief):** `/health` and `/metrics`.
**Assignment 1 observability admin endpoints (kept as-is):** `/admin/fault`, `/admin/cardinality-test`, `/admin/reset-limits`.

**Callers updated:** the storefront page (`home_page`) and both test scripts (`test_api.py`, `caller.py`) call the new `/api/v1/...` endpoints. Legacy aliases remain so any old caller still works.

### 8. Automated Tests — Valid, Invalid, Repeated

`test_api.py` exercises the three required cases plus rate limiting:

```bash
py -3 test_api.py
```

```
--- TEST 1: Valid Request ---
Add to cart status: 200          (cart: 2 items, Total: PKR 2998.0)
Place order status: 201          Location: /api/v1/orders/ord-..., Idempotent-Replay: false
>>> TEST 1 PASSED: Valid Request returned 201 Created with Location header.

--- TEST 2: Invalid Input Validation & Consistent Error Format ---
Empty Cart Order Status: 400     error.code = BAD_REQUEST
Invalid Email Status: 422         error.code = VALIDATION_ERROR (details mention customer_email)
Negative Quantity Status: 422     error.code = VALIDATION_ERROR
>>> TEST 2 PASSED: Invalid inputs properly rejected with consistent error envelope.

--- TEST 3: Idempotency (Safe Repeats) ---
1st Response Status: 201, Order ID: ord-3793fe8c, Replay Header: false
2nd Response Status: 201, Order ID: ord-3793fe8c, Replay Header: true
Verified database: exactly 1 order exists for ID ord-3793fe8c (NO duplicates created).
>>> TEST 3 PASSED: Repeated request safely handled via Idempotency-Key.

--- TEST 4: Rate Limiting & 429 Too Many Requests ---
Request #6: Status=429, X-RateLimit-Remaining=0, Retry-After=10
>>> TEST 4 PASSED: Rate limit accepted 5 requests, rejected 6th with 429 & Retry-After header.

=================================================================
 ALL 4 TESTS PASSED SUCCESSFULLY!
=================================================================
```

### 9. Resilient Python Caller

`caller.py` is a small Python service that calls `POST /api/v1/orders` several times in one run. It uses the **Idempotency-Key** header so retries are safe, and adds a **timeout**, **limited retries with exponential backoff** (only on transient failures), and a **3-state circuit breaker**.

**Settings:**

| Setting | Value |
|---|---|
| Request timeout | 1.5 s |
| Retry limit | 3 attempts |
| Backoff strategy | Exponential — initial 0.5 s, multiplier ×2 (0.5s → 1.0s → 2.0s) |
| Circuit breaker failure threshold | 3 consecutive failures → OPEN |
| Circuit breaker recovery cooldown | 4.0 s → HALF-OPEN canary |
| States | CLOSED → OPEN → HALF-OPEN → CLOSED |

**Demonstration (uses an injected `503` server fault; rate limiting is shown separately in Test 4 above):**

```bash
py -3 caller.py
```

```
>>> PHASE 1: Normal Succeeding Operations (Breaker: CLOSED) <<<
Call #1 (Healthy Checkout)   -> SUCCESS [HTTP 201 Created] (Order ID ..., Replay: false)
Call #2 (Healthy Checkout)   -> SUCCESS [HTTP 201 Created]

>>> PHASE 2: Transient Server Outage Injected (503 Service Unavailable) <<<
Call #3 (Fault Injected)     -> Attempt 1/3 ... TRANSIENT FAILURE [HTTP 503]
                                [Backoff] Waiting 0.50s -> Attempt 2/3 ... TRANSIENT FAILURE
                                [Backoff] Waiting 1.00s -> Attempt 3/3 ... TRANSIENT FAILURE
                                [Failure] All 3 attempts exhausted.   (failure #1)
Call #4 (Fault Injected)     -> ... 3 retries, fail.                       (failure #2)
Call #5 (Fault Injected)     -> ... 3 retries, fail.
   [CircuitBreaker] Failure threshold reached (3/3)! State tripped: CLOSED -> OPEN.

>>> PHASE 3: Fast-Failing While Breaker is OPEN <<<
Call #6 (Fast-Fail while OPEN) -> [FAST FAIL] Circuit breaker is OPEN (4.0s cooldown remaining). Call blocked locally. Request ABORTED without network traffic.
Call #7 (Fast-Fail while OPEN) -> [FAST FAIL] ... Call blocked locally.

>>> PHASE 4: Server Healing & Breaker Recovery <<<
1. Clearing server fault (Server returns to 200 OK)
2. Waiting for recovery cooldown period (4.0s)
3. Canary trial request:
   [CircuitBreaker] Recovery cooldown elapsed (4.54s >= 4.0s).
   [CircuitBreaker] State transitioned: OPEN -> HALF-OPEN.
   Call #8 -> Attempt 1/3 -> SUCCESS [HTTP 201 Created]
   [CircuitBreaker] Trial request SUCCEEDED! HALF-OPEN -> CLOSED (Fully Recovered).
4. Call #9 (Post-Recovery) -> SUCCESS [HTTP 201 Created] (Breaker: CLOSED)

=================================================================
 CALLER SUITE DEMONSTRATION COMPLETE: ALL PHASES VERIFIED
=================================================================
```

This shows all four required behaviours: **succeeding** (Phase 1), **retrying a failure** with backoff (Phase 2), **blocking calls while the breaker is OPEN** (Phase 3), and **recovering** via HALF-OPEN → CLOSED (Phase 4).

---

## Part B: Add a gRPC Service (30 marks)

### Overview & Design Choice

Part B extracts the **order cancellation** operation (`CancelOrder`) from the REST API and re-implements it as a **standalone gRPC service running in its own process/container**. The HTTP `PATCH /api/v1/orders/{order_id}` endpoint is kept unchanged. A read-side `GetOrder` RPC is also exposed.

Both transports bind to the **same source of truth** (the SQLite database in `data/cristaux_orders.db`) and the **same business rules** via the shared module `app/orders_repository.py`. The gRPC servicer calls `db_cancel_order(...)` directly — it is **not** an HTTP wrapper around the old endpoint, so the two paths stay independent while remaining consistent.

### New / Changed Files

| File | Purpose |
|---|---|
| `proto/order_service.proto` | RPC + message contract (`package cristaux.orders`) |
| `proto/order_service_pb2.py`, `proto/order_service_pb2_grpc.py` | Generated protobuf + gRPC stubs (grpc 1.84.0) |
| `grpc_server.py` | Standalone gRPC server process + `OrderServiceServicer` handler |
| `grpc_client.py` | Python CLI client (deadline, input args, error diagnostics) |
| `app/orders_repository.py` | Shared persistence + business rules, used by both REST and gRPC |
| `Dockerfile.grpc` + `docker-compose.yml` | Runs the gRPC service as its own container (`grpc-service`, port 50051) |
| `test_grpc_vs_http.py` | Dual-protocol comparison suite (success + 2 failures through both versions) |
| `filebeat/filebeat.yml` | Updated to ship `grpc-service` logs to Kibana alongside `app` |

**Code generation command** (regenerates `proto/order_service_pb2.py` and `proto/order_service_pb2_grpc.py` from the `.proto`; run from the project root with `grpcio-tools` installed):
```bash
py -3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. proto/order_service.proto
```

> Reference: the gRPC server/client structure follows the course **gRPC workshop** (week 1 Midnight Launch). No third-party code was copied; only the standard `grpcio` / `grpcio-tools` patterns were reused.

### How to Run

**1. Docker (both services + observability stack):**
```bash
docker compose up -d --build
# REST API    -> http://localhost:8000
# gRPC service -> grpc://localhost:50051
```

**2. Standalone (local Python, no Docker):**
```bash
# Terminal 1 - REST API
py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2 - gRPC server
py -3 grpc_server.py

# Terminal 3 - gRPC client (accepts input, sets deadline, reports results/errors)
py -3 grpc_client.py --order-id ord-12345678 --reason customer_changed_mind --deadline 3
py -3 grpc_client.py --order-id ord-ghost-99999999 --deadline 3          # NOT_FOUND
py -3 grpc_client.py --order-id ord-12345678 --deadline 0.001            # DEADLINE_EXCEEDED
py -3 grpc_client.py --get --order-id ord-12345678                      # GetOrder
```

**3. Dual-protocol comparison (needs both servers running):**
```bash
py -3 test_grpc_vs_http.py
```

### Call Path Diagrams

The brief asks for both call paths, including the **generated stub** and the **server handler**.

**HTTP REST path (FastAPI, kept from Part A):**
```
Python client (requests.Session)
   |  PATCH /api/v1/orders/{order_id}   header: x-request-id
   v
FastAPI middleware  (app/main.py: observability_middleware)
   - generates / propagates x-request-id
   - records http_request_duration_seconds histogram
   - emits structured JSON log: {request_id, status_code, duration_ms}
   v
update_order_status_v1()  ->  db_cancel_order(order_id, reason)
   v
app/orders_repository.py   (shared business rules)
   - returns NOT_FOUND | ALREADY_CANCELLED | ALREADY_FULFILLED | SUCCESS
   v
SQLite  (data/cristaux_orders.db, WAL mode)   <-- shared source of truth
   v
HTTP 200 OK  |  404 Not Found  |  409 Conflict     (response carries x-request-id header)
   v
Filebeat  ->  Elasticsearch / Kibana   (container.name = "app")
```

**gRPC path (new Part B process):**
```
grpc_client.py   (argparse CLI, deadline, x-request-id metadata)
   |
   |  order_service_pb2_grpc.OrderServiceStub(channel)   <-- GENERATED STUB
   |  stub.CancelOrder(request, timeout=deadline,
   |                  metadata=(('x-request-id', req_id),))
   v
HTTP/2 + protobuf   ->   127.0.0.1:50051
   v
grpc.server(ThreadPoolExecutor)   in grpc_server.py
   v
OrderServiceServicer.CancelOrder(request, context)   <-- SERVER HANDLER
   - extract_request_id(context)  <-- reads invocation metadata
   - structured JSON log: {request_id, rpc, status_code, duration_ms}
   - db_cancel_order(order_id, reason)   <-- SAME shared business rules
   v
app/orders_repository.py   (shared business rules)   <-- SAME module as REST
   v
SQLite  (data/cristaux_orders.db, WAL mode)   <-- SAME source of truth
   v
CancelOrderResponse  OR  context.abort(StatusCode.NOT_FOUND / FAILED_PRECONDITION)
   + context.set_trailing_metadata(('x-request-id', request_id))
   v
gRPC status  OK (0) | NOT_FOUND (5) | FAILED_PRECONDITION (9) | DEADLINE_EXCEEDED (4)
   v
Filebeat  ->  Elasticsearch / Kibana   (container.name = "grpc-service")
```

Both paths converge on `orders_repository.py` + SQLite, which guarantees identical business rules and a single source of truth. Because the gRPC servicer imports and calls the repository directly (no HTTP hop), this is a real second implementation of the operation, not a wrapper.

### Successful & Failed Requests — Status Explanation

Running `py -3 test_grpc_vs_http.py` exercises one successful and two failed requests through **both** transports against the shared DB. Condensed output:

**1. Successful cancellation of a pending order**
```
[HTTP REST]  PATCH /api/v1/orders/ord-http-succ-73c726
  HTTP Status Code: 200 OK
  Response: {'order_id':'ord-http-succ-73c726','status':'cancelled','reason':'customer_changed_mind_via_http'}

[gRPC]      cristaux.orders.OrderService/CancelOrder
  gRPC Status Code: OK (0)
  Response: order_id='ord-grpc-succ-bb67e2', status='cancelled', reason='customer_changed_mind_via_grpc'

>>> VERIFICATION: Both orders verified as 'cancelled' in shared SQLite database.
```
HTTP `200 OK` means the resource was found and its state changed; gRPC `OK (0)` is the unary-RPC success code with a populated `CancelOrderResponse`.

**2. Failed request — non-existent order**
```
[HTTP REST]  Status 404 Not Found   error.code = RESOURCE_NOT_FOUND
[gRPC]       Status NOT_FOUND (5)   "Order 'ord-ghost-99999999' was not found in the database."
```
HTTP maps the missing resource to `404`; gRPC uses the semantic status code `NOT_FOUND (5)` and carries a human-readable `details` string.

**3. Failed request — invalid state transition (already cancelled)**
```
[HTTP REST]  Status 409 Conflict   error.code = CONFLICT
[gRPC]       Status FAILED_PRECONDITION (9)   "Order '...' is already in cancelled state."
```
HTTP signals a state conflict with `409`; gRPC uses `FAILED_PRECONDITION (9)` because the order was not in the required `pending` state for the transition.

**4. Failed request — client deadline exceeded (gRPC only)**
```
py -3 grpc_client.py --order-id ord-ghost-99999999 --deadline 0.001 --host 127.0.0.1:50052
  gRPC Status: DEADLINE_EXCEEDED (4)
  [Diagnosis]: Server failed to respond within the 0.001s deadline.
```
With `--deadline 0.001` against an unreachable port the client surfaces `DEADLINE_EXCEEDED (4)`; the HTTP equivalent is `408 Request Timeout` / `504 Gateway Timeout`.

**Status code mapping:**

| Scenario | HTTP Status | gRPC Status Code | Meaning |
|---|---|---|---|
| Successful cancel | 200 OK | OK (0) | Operation fulfilled; order state modified |
| Missing order | 404 Not Found | NOT_FOUND (5) | `order_id` does not exist in source of truth |
| Already cancelled/fulfilled | 409 Conflict | FAILED_PRECONDITION (9) | Order not in valid `pending` state for the transition |
| Client timeout | 408 / 504 | DEADLINE_EXCEEDED (4) | Server did not reply within client deadline |
| Server unreachable | connection refused | UNAVAILABLE (14) | gRPC server not reachable at host:port |

### Trace Correlation Across the gRPC Boundary

A1 structured logging is preserved on the gRPC side and correlated across the boundary via `x-request-id`:

1. The gRPC client generates a `request_id` (UUID) and sends it as gRPC call metadata `('x-request-id', req_id)`.
2. The server's `extract_request_id(context)` reads it from `context.invocation_metadata()` and writes it into every structured JSON log line (`request_id`, `rpc`, `order_id`, `status_code`, `duration_ms`) — same schema as the FastAPI middleware logs.
3. The server echoes the id back with `context.set_trailing_metadata(('x-request-id', request_id))`, so the client can correlate its own records with the server-side logs.
4. Filebeat's `decode_json_fields` lifts `request_id` to a top-level field for both the `app` and `grpc-service` containers, so in Kibana you can filter by a single `request_id` and see both the HTTP leg and the gRPC leg of the same logical operation in one view.

Example gRPC server log line (identical schema to the REST app):
```json
{"@timestamp":"2026-10-18T05:33:56.975Z","service":"Cristaux Jewellery gRPC Service","level":"INFO","message":"gRPC CancelOrder succeeded","request_id":"trace-grpc-e6eb441f","rpc":"CancelOrder","order_id":"ord-grpc-succ-bb67e2","status_code":"OK","duration_ms":17.31}
```

---

## Part C: Extend the Metrics (30 marks)

### 1. A1 Metrics Audit

**Useful (kept as-is):**

| Metric | Type | Why it stays |
|---|---|---|
| `jewellery_orders_placed_total{category}` | Counter | Orders placed by product category |
| `jewellery_orders_cancelled_total{reason}` | Counter | Cancellations by reason |
| `jewellery_pending_orders_count` | Gauge | Queue depth for fulfilment |
| `jewellery_active_carts_count` | Gauge | Active shopping carts |
| `http_request_duration_seconds{method,path,status}` | Histogram | HTTP latency by route + status |
| `jewellery_order_processing_seconds` | Summary | Checkout processing time |

**Missing / fixed:**

| Issue | Finding | Fix / addition |
|---|---|---|
| gRPC service had **no metrics at all** | Prometheus could not scrape Part B | Added `/metrics` on port 50052 + 3 new metrics (below); added a `grpc-service` scrape job |
| No error-rate by method/status | Derivable from a call counter | `grpc_calls_total{rpc_method,status}` — error rate = `rate(...{status!="OK"})`, so no separate error counter is needed |
| No concurrency metric | No visibility into in-flight work | Added `grpc_in_flight_calls{rpc_method}` |
| Only `pending` tracked as a gauge | No order-state distribution | Added `jewellery_orders_by_status{status}` (missing project metric) computed from the shared DB |
| `http_request_duration_seconds` used **raw `request.url.path`** as a label | Embedded the real `order_id`/`cart_id`/`product_id` → unbounded cardinality (the brief warns against this) | `normalize_path()` now uses the route template (`/api/v1/orders/{order_id}`), so the `path` label set stays bounded |
| `jewellery_orders_cancelled_total{reason}` | `reason` is a customer-provided string (semi-unbounded) | Flagged; kept for A1 dashboard compatibility. In practice it stays small; would normalize to a reason enum if it grew |

`demo_requests_total{request_id}` from A1's Part E cardinality experiment is intentionally unbounded — it is the *example* of the anti-pattern, not a metric to fix.

### 2. New Metrics

| Metric | Purpose | Type | Unit | Labels (bounded) | Code location | Client or server? | Example query |
|---|---|---|---|---|---|---|---|
| `grpc_calls_total` | Calls and error rate by RPC method and status | Counter | calls | `rpc_method` ∈ {CancelOrder, GetOrder}, `status` ∈ {OK, NOT_FOUND, FAILED_PRECONDITION, …} | `grpc_server.py` (`record_rpc`) | — | `sum by (rpc_method, status) (rate(grpc_calls_total[5m]))` |
| `grpc_request_duration_seconds` | Handler latency for p50/p95 | Histogram | seconds | `rpc_method`, `status` | `grpc_server.py` (`record_rpc`) | **Server** (handler wraps call with `perf_counter`) | `histogram_quantile(0.95, sum by (le, rpc_method) (rate(grpc_request_duration_seconds_bucket[5m])))` |
| `grpc_in_flight_calls` | Concurrency / stuck handlers | Gauge | calls | `rpc_method` | `grpc_server.py` (handler `inc`/`dec` in `finally`) | — | `grpc_in_flight_calls` |
| `jewellery_orders_by_status` | Order-state distribution (missing A1 metric) | Gauge | orders | `status` ∈ {pending, cancelled, fulfilled} | `app/main.py` (`OrderStatusCollector`) + `app/orders_repository.count_orders_by_status` | — | `jewellery_orders_by_status` |

**Duration is measured at the server** for both transports: the gRPC handler and the FastAPI middleware each wrap the call with `time.perf_counter()`. No client-side timing is used for these metrics.

**In-flight vs message size:** I chose **in-flight calls**. The operations are unary RPCs with small, fixed-size protobuf payloads (a few hundred bytes), so message size is near-constant and uninformative; in-flight calls reveal concurrency and stuck/slow handlers, which is the more useful signal.

**Bounded labels:** all label sets are small and fixed. `request_id` / `x-request-id` / trace IDs are **never** used as labels — they stay only in the structured JSON log lines (where high cardinality is fine) and in the gRPC trailing metadata for correlation.

### 3. Run the Repeatable Traffic

Start both services, then generate a bounded mix of success + failure gRPC calls to populate the panels:

```bash
# Terminal 1 - REST API   (HTTP operation side)
py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2 - gRPC server (serves RPC on 50051 + /metrics on 50052)
py -3 grpc_server.py

# Terminal 3 - repeatable gRPC traffic (10 rounds x 5 RPCs = ~50 calls)
py -3 grpc_seed_traffic.py --rounds 10 --sleep 0.1
```

`grpc_seed_traffic.py` produces a bounded status mix — `OK` (cancel a freshly-seeded order / GetOrder on an existing one), `NOT_FOUND` (non-existent order), `FAILED_PRECONDITION` (re-cancelling an already-cancelled order) — so the calls-by-status and error-rate panels have data for every status.

For the HTTP operation side, the existing `seed_traffic.py` already drives `PATCH /api/v1/orders/{order_id}` cancels/fulfils, which populate `http_request_duration_seconds` for the comparison panels.

### 4. Grafana Dashboard

A new dashboard **"Cristaux - Part C: gRPC vs HTTP Operation Metrics"** is provisioned at `grafana/provisioning/dashboards/part_c_grpc_dashboard.json` (auto-loaded by Grafana). It shows gRPC metrics **beside** the HTTP cancel operation (`PATCH /api/v1/orders/{order_id}`):

| Panel | gRPC | HTTP (same operation) |
|---|---|---|
| Calls by method & status | `sum by (rpc_method, status) (rate(grpc_calls_total[5m]))` | `sum by (status) (rate(http_request_duration_seconds_count{method="PATCH",path="/api/v1/orders/{order_id}"}[5m]))` |
| Error rate | `sum by (rpc_method) (rate(grpc_calls_total{status!="OK"}[5m]))` | `sum (rate(http_request_duration_seconds_count{...,status!~"2.."}[5m]))` |
| Duration p50 & p95 (5m) | `histogram_quantile(0.50/0.95, sum by (le, rpc_method) (rate(grpc_request_duration_seconds_bucket[5m])))` | `histogram_quantile(0.50/0.95, sum by (le) (rate(http_request_duration_seconds_bucket{method="PATCH",...}[5m])))` |
| In-flight calls | `grpc_in_flight_calls` | — |
| Orders by status (missing A1 metric) | `jewellery_orders_by_status` | — |

All time windows are **5 minutes** (`[5m]`), shown in each panel title/description. Duration panels are server-side for both transports. Open it at http://localhost:3000 → Dashboards → *Cristaux - Part C: gRPC vs HTTP Operation Metrics*.

### 5. Dashboard Evidence

Run the stack and both seed scripts to populate the panels, then capture screenshots for the submission:
```bash
docker compose up -d --build
py -3 seed_traffic.py            # HTTP operation traffic
py -3 grpc_seed_traffic.py       # gRPC operation traffic (OK / NOT_FOUND / FAILED_PRECONDITION)
```

**Part C dashboard — "Cristaux - Part C: gRPC vs HTTP Operation Metrics"** (gRPC metrics beside the HTTP operation) — screenshots in `REPORT.docx` / `REPORT.pdf`.

**A1 dashboard — "Jewellery Store Observability Dashboard"** (kept from Assignment 1, still scraped) — screenshots in `REPORT.docx` / `REPORT.pdf`.

> Keep the `data/` volume and Docker volumes out of the submission (already in `.gitignore`).

---

## Appendix: Assignment 1 Observability (still running)

The Assignment 1 observability stack is preserved and runs alongside the Assignment 2 services.

### Latency Anomaly Test (Fault Injection)
```bash
# Trigger a 500ms artificial delay
curl -X POST http://localhost:8000/admin/fault -H "Content-Type: application/json" -d "{\"delay_ms\": 500}"
# Observe the p95 latency spike in Grafana, then reset
curl -X POST http://localhost:8000/admin/fault -H "Content-Type: application/json" -d "{\"delay_ms\": 0}"
```

### Cardinality Explosion Test
```bash
curl http://localhost:8000/admin/cardinality-test
# Then run count(demo_requests_total) in Prometheus to watch time-series proliferation.
```

### Observability UIs
- **Prometheus:** [http://localhost:9090](http://localhost:9090)
- **Grafana:** [http://localhost:3000](http://localhost:3000) (admin / admin) → Dashboards → *Jewellery Store Observability Dashboard*
- **Kibana:** [http://localhost:5601](http://localhost:5601) → Create Data View `app-logs-*` → Analytics → Discover (now includes both `app` and `grpc-service` logs)

---

## Cleanup & Teardown

Stop containers while keeping data:
```bash
docker compose down
```

Remove containers, networks, and all stored data volumes:
```bash
docker compose down -v
```
