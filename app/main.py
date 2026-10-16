"""
Cristaux Jewellery - Luxury E-Commerce Application with Observability & REST Best Practices.

Part A: E-Commerce Store Frontend & RESTful APIs (Products, Cart, Orders)
        - OpenAPI Specification (v2.0.0)
        - Idempotency via Idempotency-Key header (Safe Repeats)
        - Rate Limiting with 429 Too Many Requests & Retry-After
        - Standardized, consistent JSON error responses
Part B: Metrics (Counter, Gauge, Histogram, Summary)
Part C: Structured JSON Logging (with x-request-id)
Part E: Fault Injection & Cardinality Explosion endpoints
"""

import json
import logging
import re
import sys
import time
import uuid
from typing import Dict, Optional, List, Literal, Any

from pydantic import BaseModel, Field, field_validator
from fastapi import FastAPI, Request, HTTPException, Query, Response, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    Summary,
    generate_latest,
)

# --------------------------------------------------------------------------
# Structured Logging Setup
# --------------------------------------------------------------------------
SERVICE_NAME = "Cristaux Jewellery"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "@timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)
            )
            + f".{int(record.msecs):03d}Z",
            "service": SERVICE_NAME,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload)


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())

logger = logging.getLogger(SERVICE_NAME)
logger.setLevel(logging.INFO)
logger.handlers = [handler]
logger.propagate = False

# --------------------------------------------------------------------------
# Prometheus Metrics Definition (Part B)
# --------------------------------------------------------------------------

# 1. COUNTERS (Monotonically increasing cumulative metrics)
ORDERS_PLACED_TOTAL = Counter(
    "jewellery_orders_placed_total",
    "Total number of jewellery orders placed.",
    ["category"],
)

ORDERS_CANCELLED_TOTAL = Counter(
    "jewellery_orders_cancelled_total",
    "Total number of jewellery orders cancelled.",
    ["reason"],
)

CARDINALITY_TEST_COUNTER = Counter(
    "demo_requests_total",
    "Counter used for Part E2 Cardinality Explosion experiment.",
    ["request_id"],
)

# 2. GAUGES (Metrics that go up and down)
PENDING_ORDERS_GAUGE = Gauge(
    "jewellery_pending_orders_count",
    "Number of orders waiting to be fulfilled.",
)

ACTIVE_CARTS_GAUGE = Gauge(
    "jewellery_active_carts_count",
    "Number of currently active user shopping carts.",
)

# 3. HISTOGRAMS (Bucketed measurements for p95/p99 latency)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path", "status"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# 4. SUMMARIES (Tracks count and sum for averages)
ORDER_PROCESSING_SUMMARY = Summary(
    "jewellery_order_processing_seconds",
    "Time taken to process and finalize an order checkout in seconds.",
)


# --------------------------------------------------------------------------
# App State & In-Memory Store
# --------------------------------------------------------------------------
app = FastAPI(
    title="Cristaux Jewellery Store API",
    description="Enterprise Luxury Jewellery RESTful E-Commerce API featuring Prometheus Metrics, Structured JSON Logging, OpenAPI 3.1 Spec, Rate Limiting, and Idempotency Protection.",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={
        "name": "Cristaux Jewellery Engineering Team",
        "email": "api@cristaux-jewellery.com",
    },
)

# In-memory database simulation
PRODUCTS = [
    {
        "id": "p1",
        "name": "Minimalist Silver Band Ring",
        "category": "rings",
        "price": 1499.0,
        "image": "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=600&q=80",
        "desc": "Elegant 925 sterling silver band, perfect for daily wear."
    },
    {
        "id": "p2",
        "name": "Blue Crystal Pendant Necklace",
        "category": "necklaces",
        "price": 2499.0,
        "image": "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=600&q=80",
        "desc": "Charming blue zirconia crystal pendant with fine silver chain."
    },
    {
        "id": "p3",
        "name": "Classic Gold Plated Hoops",
        "category": "earrings",
        "price": 999.0,
        "image": "https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=600&q=80",
        "desc": "Lightweight 18k gold-plated hoop earrings."
    },
    {
        "id": "p4",
        "name": "Freshwater Pearl Bracelet",
        "category": "bracelets",
        "price": 1899.0,
        "image": "https://images.unsplash.com/photo-1611591475285-a36ad5e14391?auto=format&fit=crop&w=600&q=80",
        "desc": "Handcrafted bracelet made with natural freshwater pearls."
    },
    {
        "id": "p5",
        "name": "Rose Gold Crystal Crown Ring",
        "category": "rings",
        "price": 1799.0,
        "image": "https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=600&q=80",
        "desc": "Rose gold plated crown ring with cubic zirconia stones."
    },
    {
        "id": "p6",
        "name": "Emerald Green Drop Earrings",
        "category": "earrings",
        "price": 1299.0,
        "image": "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=600&q=80",
        "desc": "Stunning emerald green glass drop earrings."
    }
]

CARTS: Dict[str, List[Dict]] = {}  # cart_id -> list of product items
ORDERS: Dict[str, Dict] = {}       # order_id -> order details

# Fault Injection State (Part E1 & Testing)
FAULT_CONFIG = {
    "delay_ms": 0.0,
    "error_rate": 0.0,
    "status_code": 0  # e.g., 503 or 500
}

# --------------------------------------------------------------------------
# Rate Limiting & Idempotency Store
# --------------------------------------------------------------------------
class InMemoryRateLimiter:
    """
    Sliding window rate limiter per client IP.
    """
    def __init__(self, limit: int = 5, window_seconds: float = 10.0):
        self.limit = limit
        self.window_seconds = window_seconds
        self.requests: Dict[str, List[float]] = {}

    def check(self, client_key: str) -> tuple[bool, int, int]:
        """
        Check if request is permitted.
        Returns: (allowed: bool, remaining: int, retry_after: int)
        """
        now = time.time()
        window_start = now - self.window_seconds
        timestamps = [t for t in self.requests.get(client_key, []) if t > window_start]

        if len(timestamps) >= self.limit:
            oldest = timestamps[0]
            retry_after = max(1, int(self.window_seconds - (now - oldest)) + 1)
            self.requests[client_key] = timestamps
            return False, 0, retry_after

        timestamps.append(now)
        self.requests[client_key] = timestamps
        remaining = self.limit - len(timestamps)
        return True, remaining, 0

    def reset(self):
        self.requests.clear()

ORDER_RATE_LIMITER = InMemoryRateLimiter(limit=5, window_seconds=10.0)

# Idempotency store: key -> {"order_id": str, "data": dict, "created_at": float}
IDEMPOTENCY_STORE: Dict[str, Dict[str, Any]] = {}


# --------------------------------------------------------------------------
# Consistent Error Response Helper & Exception Handlers
# --------------------------------------------------------------------------
def make_error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    content = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "timestamp": now,
        }
    }
    return JSONResponse(status_code=status_code, content=content, headers=headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    simplified = [
        {
            "field": " -> ".join(str(loc) for loc in err.get("loc", []) if loc != "body"),
            "issue": err.get("msg"),
            "type": err.get("type"),
        }
        for err in errors
    ]
    return make_error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message="The request payload failed input schema validation.",
        details=simplified,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code_map = {
        400: "BAD_REQUEST",
        404: "RESOURCE_NOT_FOUND",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        429: "RATE_LIMIT_EXCEEDED",
        500: "INTERNAL_SERVER_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }
    code = code_map.get(exc.status_code, "ERROR")
    headers = getattr(exc, "headers", None)
    return make_error_response(
        status_code=exc.status_code,
        code=code,
        message=str(exc.detail),
        headers=headers,
    )


# --------------------------------------------------------------------------
# Middleware: Request ID, Logging, Fault Injection & Duration Histogram
# --------------------------------------------------------------------------
@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = time.perf_counter()

    # Fault injection: delay (Part E1)
    if FAULT_CONFIG.get("delay_ms", 0) > 0 and not request.url.path.startswith("/admin/fault"):
        time.sleep(FAULT_CONFIG["delay_ms"] / 1000.0)

    # Fault injection: status code simulation (e.g. 503 Service Unavailable)
    if FAULT_CONFIG.get("status_code", 0) > 0 and not request.url.path.startswith("/admin/fault"):
        status_code = int(FAULT_CONFIG["status_code"])
        duration = time.perf_counter() - started
        HTTP_REQUEST_DURATION.labels(
            method=request.method, path=request.url.path, status=str(status_code)
        ).observe(duration)
        logger.error(
            f"simulated fault status code {status_code}",
            extra={
                "extra_fields": {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": round(duration * 1000, 2),
                }
            },
        )
        return make_error_response(
            status_code=status_code,
            code="SERVICE_UNAVAILABLE" if status_code == 503 else "INTERNAL_SERVER_ERROR",
            message=f"Simulated fault injection server failure (HTTP {status_code}).",
            headers={"x-request-id": request_id},
        )

    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as exc:
        status_code = 500
        duration = time.perf_counter() - started
        HTTP_REQUEST_DURATION.labels(
            method=request.method, path=request.url.path, status=str(status_code)
        ).observe(duration)
        logger.error(
            "unhandled exception occurred",
            extra={
                "extra_fields": {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": round(duration * 1000, 2),
                    "error": str(exc),
                }
            },
        )
        raise exc

    duration = time.perf_counter() - started

    # Record Histogram Metric
    HTTP_REQUEST_DURATION.labels(
        method=request.method, path=request.url.path, status=str(status_code)
    ).observe(duration)

    # Output Structured Log
    logger.info(
        "request processed",
        extra={
            "extra_fields": {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": round(duration * 1000, 2),
            }
        },
    )

    response.headers["x-request-id"] = request_id
    return response


# --------------------------------------------------------------------------
# Domain API Models & Input Validation
# --------------------------------------------------------------------------
class AddToCartRequest(BaseModel):
    cart_id: str = Field(..., min_length=3, max_length=64, description="Unique cart session identifier")
    product_id: str = Field(..., min_length=2, max_length=16, description="Catalog product ID (e.g. p1, p2)")
    quantity: int = Field(default=1, ge=1, le=20, description="Quantity to add (1 to 20)")

class OrderRequest(BaseModel):
    cart_id: str = Field(..., min_length=3, max_length=64, description="Active cart ID to checkout")
    customer_email: str = Field(..., description="Customer contact email address")

    @field_validator("customer_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(email_regex, v.strip()):
            raise ValueError("Invalid email format. Must be a valid email (e.g., user@example.com)")
        return v.strip().lower()

class UpdateOrderStatusRequest(BaseModel):
    status: Literal["cancelled", "fulfilled"] = Field(..., description="Target status ('cancelled' or 'fulfilled')")
    reason: Optional[str] = Field("customer_request", max_length=120, description="Reason for status update")

class CancelOrderRequest(BaseModel):
    reason: str = "customer_changed_mind"

class FaultConfigRequest(BaseModel):
    delay_ms: float = Field(default=0.0, ge=0.0, description="Artificial latency delay in milliseconds")
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="Probability of triggering errors (0.0 to 1.0)")
    status_code: int = Field(default=0, description="HTTP status code to simulate (e.g. 503, 500, or 0 to disable)")


# --------------------------------------------------------------------------
# Interactive UI Endpoint (Root Homepage)
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home_page():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Cristaux Jewellery — Haute Joaillerie</title>
        <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Montserrat:wght@300;400;500;600&display=swap" rel="stylesheet">
        <style>
            :root {
                --purple-primary: #6B21A8;
                --purple-dark: #3B0764;
                --purple-light: #A855F7;
                --purple-soft: #EDE9FE;
                --gold-accent: #F59E0B;
                --dark: #0F0A1A;
                --card-bg: #1E152A;
                --text-light: #F3E8FF;
                --text-muted: #C084FC;
            }
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body {
                font-family: 'Montserrat', sans-serif;
                background-color: var(--dark);
                color: var(--text-light);
                line-height: 1.6;
            }
            header {
                background: rgba(15, 10, 26, 0.95);
                border-bottom: 1px solid rgba(168, 85, 247, 0.3);
                padding: 1.5rem 3rem;
                display: flex;
                justify-content: space-between;
                align-items: center;
                position: sticky;
                top: 0;
                z-index: 100;
                backdrop-filter: blur(10px);
            }
            .brand {
                font-family: 'Cinzel', serif;
                font-size: 1.8rem;
                letter-spacing: 4px;
                color: var(--purple-light);
                text-decoration: none;
                text-transform: uppercase;
                font-weight: 700;
            }
            .nav-links a {
                color: var(--text-light);
                margin-left: 2rem;
                text-decoration: none;
                font-size: 0.9rem;
                letter-spacing: 1px;
                transition: color 0.3s;
            }
            .nav-links a:hover { color: var(--purple-light); }
            
            .hero {
                text-align: center;
                padding: 5rem 2rem 3rem;
                background: linear-gradient(180deg, rgba(107, 33, 168, 0.35) 0%, rgba(15, 10, 26, 1) 100%);
            }
            .hero h1 {
                font-family: 'Cinzel', serif;
                font-size: 3rem;
                color: var(--purple-soft);
                margin-bottom: 1rem;
                letter-spacing: 2px;
            }
            .hero p {
                max-width: 600px;
                margin: 0 auto;
                color: var(--text-muted);
                font-weight: 300;
            }
            
            .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
            .section-title {
                font-family: 'Cinzel', serif;
                font-size: 1.8rem;
                color: var(--purple-light);
                margin-bottom: 2rem;
                text-align: center;
                letter-spacing: 2px;
            }
            
            .grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
                gap: 2rem;
            }
            .card {
                background-color: var(--card-bg);
                border: 1px solid rgba(168, 85, 247, 0.25);
                border-radius: 8px;
                overflow: hidden;
                transition: transform 0.3s, border-color 0.3s;
            }
            .card:hover {
                transform: translateY(-5px);
                border-color: var(--purple-light);
                box-shadow: 0 8px 25px rgba(168, 85, 247, 0.2);
            }
            .card-img {
                width: 100%;
                height: 260px;
                object-fit: cover;
            }
            .card-body { padding: 1.5rem; }
            .card-title {
                font-family: 'Cinzel', serif;
                font-size: 1.2rem;
                color: var(--purple-soft);
                margin-bottom: 0.5rem;
            }
            .card-desc {
                font-size: 0.85rem;
                color: var(--text-muted);
                margin-bottom: 1rem;
                height: 40px;
            }
            .card-footer {
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-top: 1px solid rgba(255,255,255,0.05);
                padding-top: 1rem;
            }
            .price {
                font-size: 1.2rem;
                font-weight: 600;
                color: var(--purple-light);
            }
            .btn {
                background: linear-gradient(135deg, #A855F7 0%, #6B21A8 100%);
                color: #FFFFFF;
                border: none;
                padding: 0.6rem 1.2rem;
                border-radius: 4px;
                font-weight: 600;
                font-size: 0.8rem;
                cursor: pointer;
                letter-spacing: 1px;
                text-transform: uppercase;
                transition: opacity 0.3s, transform 0.2s;
            }
            .btn:hover { opacity: 0.95; transform: scale(1.02); }

            .obs-panel {
                margin-top: 4rem;
                background: rgba(107, 33, 168, 0.15);
                border: 1px solid var(--purple-light);
                border-radius: 8px;
                padding: 2rem;
                text-align: center;
            }
            .obs-panel h3 { font-family: 'Cinzel', serif; color: var(--purple-light); margin-bottom: 1rem; }
            .obs-links { display: flex; justify-content: center; gap: 1.5rem; flex-wrap: wrap; margin-top: 1rem; }
            .obs-links a {
                color: var(--purple-soft);
                text-decoration: none;
                background: #2D1B4E;
                padding: 0.6rem 1.2rem;
                border-radius: 4px;
                border: 1px solid rgba(168, 85, 247, 0.4);
                font-size: 0.85rem;
            }
            .obs-links a:hover { background: var(--purple-light); color: #FFF; }
            
            footer {
                text-align: center;
                padding: 3rem;
                border-top: 1px solid rgba(255,255,255,0.05);
                color: var(--text-muted);
                font-size: 0.8rem;
                margin-top: 4rem;
            }
        </style>
    </head>
    <body>
        <header>
            <a href="/" class="brand">CRISTAUX JEWELLERY</a>
            <div class="nav-links">
                <a href="#catalog">Collections</a>
                <a href="#orders">My Orders</a>
                <a href="/docs" target="_blank">Swagger OpenAPI Docs</a>
                <a href="#about">About Us</a>
            </div>
        </header>

        <section class="hero">
            <h1>CRISTAUX JEWELLERY</h1>
            <p>Everyday stylish & affordable luxury jewellery for every special occasion.</p>
        </section>

        <div class="container" id="catalog">
            <h2 class="section-title">Our Collection</h2>
            <div class="grid">
                <!-- Cards rendered dynamically -->
                """ + "".join([f"""
                <div class="card">
                    <img src="{p['image']}" class="card-img" alt="{p['name']}">
                    <div class="card-body">
                        <h3 class="card-title">{p['name']}</h3>
                        <p class="card-desc">{p['desc']}</p>
                        <div class="card-footer">
                            <span class="price">PKR {p['price']:,.2f}</span>
                            <button class="btn" onclick="orderItem('{p['id']}', '{p['name']}')">Order Now</button>
                        </div>
                    </div>
                </div>
                """ for p in PRODUCTS]) + """
            </div>

            <!-- Active Orders & Cancellation Section -->
            <div style="margin-top: 4rem;" id="orders">
                <h2 class="section-title">Your Active Orders</h2>
                <div id="orders-list" style="background: var(--card-bg); border: 1px solid rgba(168, 85, 247, 0.25); border-radius: 8px; padding: 1.5rem; text-align: center;">
                    <p style="color: var(--text-muted);">Loading orders...</p>
                </div>
            </div>

            <!-- About Us Section -->
            <div style="margin-top: 5rem; margin-bottom: 2rem;" id="about">
                <h2 class="section-title">About Cristaux Jewellery</h2>
                <div style="background: var(--card-bg); border: 1px solid rgba(168, 85, 247, 0.25); border-radius: 8px; padding: 2rem; max-width: 800px; margin: 0 auto; text-align: center; color: var(--text-light);">
                    <p style="margin-bottom: 1rem;">At <strong>Cristaux Jewellery</strong>, we believe elegance should be effortless. Crafting handcrafted silver, gold-plated, and crystal statement pieces designed to make every occasion memorable.</p>
                    <p style="color: var(--text-muted); font-size: 0.9rem;">Designed with timeless artistry, RESTful standard practices, and monitored with real-time Prometheus telemetry.</p>
                </div>
            </div>
        </div>

        <footer>
            <p>&copy; 2026 Cristaux Jewellery Store. Enterprise Software Development Assignment 1 Extension.</p>
        </footer>

        <script>
            async function fetchAllOrders() {
                try {
                    const res = await fetch('/api/v1/orders');
                    if (res.ok) {
                        const data = await res.json();
                        renderOrders(data.orders || []);
                    }
                } catch (e) {
                    console.error("Failed to fetch orders:", e);
                }
            }

            async function orderItem(productId, productName) {
                const cartId = 'cart-' + Math.floor(Math.random() * 10000);
                const idempotencyKey = 'order-' + Date.now() + '-' + Math.random().toString(36).substring(2, 8);
                
                // 1. Add to cart via RESTful endpoint
                await fetch('/api/v1/cart/items', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({cart_id: cartId, product_id: productId, quantity: 1})
                });
                
                // 2. Checkout order via RESTful endpoint with Idempotency-Key
                const res = await fetch('/api/v1/orders', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Idempotency-Key': idempotencyKey
                    },
                    body: JSON.stringify({cart_id: cartId, customer_email: 'vip@cristaux.com'})
                });
                
                if (res.status === 201) {
                    const data = await res.json();
                    await fetchAllOrders();
                    alert('Order Placed Successfully! Order ID: ' + data.order_id);
                } else {
                    const err = await res.json();
                    alert('Order Failed: ' + (err.error ? err.error.message : 'Error'));
                }
            }

            async function cancelOrder(orderId) {
                // Cancel order via RESTful PATCH endpoint
                const res = await fetch('/api/v1/orders/' + orderId, {
                    method: 'PATCH',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({status: 'cancelled', reason: 'customer_cancelled_via_ui'})
                });
                
                if (res.ok) {
                    await fetchAllOrders();
                    alert('Order ' + orderId + ' has been cancelled.');
                } else {
                    const err = await res.json();
                    alert('Cancellation failed: ' + (err.error ? err.error.message : 'Error'));
                }
            }

            function renderOrders(orders) {
                const container = document.getElementById('orders-list');
                if (!orders || orders.length === 0) {
                    container.innerHTML = '<p style="color: var(--text-muted);">No active orders placed yet. Place an order above to view management options.</p>';
                    return;
                }

                let html = '<table style="width:100%; text-align:left; border-collapse:collapse; color:var(--text-light);">';
                html += '<tr style="border-bottom:1px solid rgba(168,85,247,0.3); color:var(--purple-light); height:40px;">' +
                        '<th>Order ID</th><th>Customer</th><th>Item(s)</th><th>Total</th><th>Status</th><th>Action</th></tr>';

                orders.forEach(o => {
                    const isCancelled = o.status === 'cancelled';
                    const isFulfilled = o.status === 'fulfilled';
                    const itemNames = (o.items || []).map(i => i.name).join(', ') || 'Jewellery Item';
                    let statusBg = '#065F46'; // pending / green
                    if (isCancelled) statusBg = '#991B1B';
                    if (isFulfilled) statusBg = '#1E3A8A';

                    html += `<tr style="border-bottom:1px solid rgba(255,255,255,0.05); height:50px;">
                        <td style="font-family:monospace; color:var(--purple-soft);">${o.order_id}</td>
                        <td style="font-size:0.85rem; color:var(--text-muted);">${o.customer_email}</td>
                        <td>${itemNames}</td>
                        <td>PKR ${o.total_amount.toLocaleString()}</td>
                        <td><span style="padding:0.2rem 0.6rem; border-radius:4px; font-size:0.8rem; background:${statusBg};">${o.status.toUpperCase()}</span></td>
                        <td>
                            ${isCancelled || isFulfilled ? `<span style="color:var(--text-muted); font-size:0.85rem;">${o.status.toUpperCase()}</span>` : 
                              `<button class="btn" style="background:#DC2626; padding:0.4rem 0.8rem;" onclick="cancelOrder('${o.order_id}')">Cancel Order</button>`}
                        </td>
                    </tr>`;
                });

                html += '</table>';
                container.innerHTML = html;
            }

            // Initial fetch & poll every 3 seconds to reflect background traffic
            fetchAllOrders();
            setInterval(fetchAllOrders, 3000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# --------------------------------------------------------------------------
# Catalog Endpoints (RESTful v1)
# --------------------------------------------------------------------------
@app.get("/api/v1/products", tags=["Catalog"], summary="List jewellery catalog")
async def get_products_v1(category: Optional[str] = Query(None, description="Filter products by category")):
    """Retrieve all available jewellery items, optionally filtered by category."""
    if category:
        filtered = [p for p in PRODUCTS if p["category"].lower() == category.lower()]
        return {"products": filtered, "count": len(filtered)}
    return {"products": PRODUCTS, "count": len(PRODUCTS)}


@app.get("/api/v1/products/{product_id}", tags=["Catalog"], summary="Get product details")
async def get_product_by_id_v1(product_id: str):
    """Retrieve details of a specific jewellery product by ID."""
    product = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product with ID '{product_id}' was not found.")
    return product


# Backward compatibility alias
@app.get("/products", include_in_schema=False)
async def get_products_legacy(category: Optional[str] = None):
    return await get_products_v1(category)


# --------------------------------------------------------------------------
# Shopping Cart Endpoints (RESTful v1)
# --------------------------------------------------------------------------
@app.get("/api/v1/cart/{cart_id}", tags=["Cart"], summary="Retrieve cart items")
async def get_cart_v1(cart_id: str):
    """View contents and total value of a shopping cart."""
    items = CARTS.get(cart_id, [])
    total = sum(item["price"] for item in items)
    return {"cart_id": cart_id, "items": items, "total_amount": total, "item_count": len(items)}


@app.post("/api/v1/cart/items", tags=["Cart"], summary="Add item to shopping cart", status_code=200)
async def add_to_cart_v1(item: AddToCartRequest):
    """Add a jewellery item to the specified shopping cart with quantity."""
    product = next((p for p in PRODUCTS if p["id"] == item.product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{item.product_id}' not found in catalog.")

    if item.cart_id not in CARTS:
        CARTS[item.cart_id] = []
        ACTIVE_CARTS_GAUGE.inc()

    for _ in range(item.quantity):
        CARTS[item.cart_id].append(product)

    logger.info(
        "item added to cart",
        extra={
            "extra_fields": {
                "cart_id": item.cart_id,
                "product_id": item.product_id,
                "quantity": item.quantity,
                "item_name": product["name"],
            }
        },
    )
    return {
        "cart_id": item.cart_id,
        "items": CARTS[item.cart_id],
        "item_count": len(CARTS[item.cart_id]),
        "total_amount": sum(p["price"] for p in CARTS[item.cart_id]),
    }


@app.delete("/api/v1/cart/{cart_id}", tags=["Cart"], summary="Clear shopping cart")
async def clear_cart_v1(cart_id: str):
    """Clear all items from a shopping cart."""
    if cart_id in CARTS:
        del CARTS[cart_id]
        ACTIVE_CARTS_GAUGE.dec()
    return {"status": "cleared", "cart_id": cart_id}


# Backward compatibility aliases
@app.post("/cart", include_in_schema=False)
async def add_to_cart_legacy(item: AddToCartRequest):
    return await add_to_cart_v1(item)


@app.delete("/cart/{cart_id}", include_in_schema=False)
async def clear_cart_legacy(cart_id: str):
    return await clear_cart_v1(cart_id)


# --------------------------------------------------------------------------
# Orders Endpoints (RESTful v1 with Idempotency & Rate Limiting)
# --------------------------------------------------------------------------
@app.get("/api/v1/orders", tags=["Orders"], summary="List all orders")
async def get_all_orders_v1():
    """Retrieve all placed orders across the system."""
    return {"orders": list(ORDERS.values()), "total_count": len(ORDERS)}


@app.get("/api/v1/orders/{order_id}", tags=["Orders"], summary="Get order by ID")
async def get_order_by_id_v1(order_id: str):
    """Retrieve details of a specific placed order."""
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")
    return order


@app.post(
    "/api/v1/orders",
    tags=["Orders"],
    summary="Place a new order (with Idempotency & Rate Limiting)",
    status_code=201,
)
async def place_order_v1(
    order_req: OrderRequest,
    request: Request,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", description="Unique client key to prevent duplicate orders upon retries"),
):
    """
    Place an order from an active shopping cart.
    - **Rate Limiting**: Maximum 5 calls per 10-second rolling window per client IP.
    - **Idempotency Protection**: Safe retries via `Idempotency-Key` header.
    - **HTTP 201 Created**: Returns created order with `Location` header.
    """
    # 1. Rate Limiting Check
    client_ip = request.client.host if request.client else "127.0.0.1"
    allowed, remaining, retry_after = ORDER_RATE_LIMITER.check(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Maximum 5 orders per 10 seconds allowed. Please retry after {retry_after} seconds.",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": "5",
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time() + retry_after)),
            },
        )

    # 2. Idempotency Check: Safe Repeats
    if idempotency_key:
        cached = IDEMPOTENCY_STORE.get(idempotency_key)
        if cached:
            logger.info(
                "idempotent order replay returned",
                extra={"extra_fields": {"idempotency_key": idempotency_key, "order_id": cached["order_id"]}},
            )
            return JSONResponse(
                status_code=201,
                content=cached["data"],
                headers={
                    "Location": f"/api/v1/orders/{cached['order_id']}",
                    "Idempotent-Replay": "true",
                    "X-RateLimit-Limit": "5",
                    "X-RateLimit-Remaining": str(remaining),
                },
            )

    # 3. Validate Cart
    cart_items = CARTS.get(order_req.cart_id)
    if not cart_items:
        raise HTTPException(status_code=400, detail=f"Cart '{order_req.cart_id}' is empty or does not exist.")

    # 4. Summary metric: time order creation execution
    start_time = time.perf_counter()

    order_id = f"ord-{uuid.uuid4().hex[:8]}"
    total_amount = sum(item["price"] for item in cart_items)
    main_category = cart_items[0]["category"]

    order = {
        "order_id": order_id,
        "customer_email": order_req.customer_email,
        "items": list(cart_items),
        "total_amount": total_amount,
        "status": "pending",
        "created_at": time.time(),
    }
    ORDERS[order_id] = order

    # Clear cart
    del CARTS[order_req.cart_id]
    ACTIVE_CARTS_GAUGE.dec()

    # Update Prometheus Metrics
    ORDERS_PLACED_TOTAL.labels(category=main_category).inc()  # Counter
    PENDING_ORDERS_GAUGE.inc()                                # Gauge

    process_duration = time.perf_counter() - start_time
    ORDER_PROCESSING_SUMMARY.observe(process_duration)         # Summary

    logger.info(
        "order placed successfully",
        extra={
            "extra_fields": {
                "order_id": order_id,
                "total_amount": total_amount,
                "items_count": len(cart_items),
                "main_category": main_category,
                "idempotency_key": idempotency_key,
            }
        },
    )

    # 5. Store in Idempotency Cache
    if idempotency_key:
        IDEMPOTENCY_STORE[idempotency_key] = {
            "order_id": order_id,
            "data": order,
            "created_at": time.time(),
        }

    return JSONResponse(
        status_code=201,
        content=order,
        headers={
            "Location": f"/api/v1/orders/{order_id}",
            "Idempotent-Replay": "false",
            "X-RateLimit-Limit": "5",
            "X-RateLimit-Remaining": str(remaining),
        },
    )


@app.patch("/api/v1/orders/{order_id}", tags=["Orders"], summary="Update order status (Cancel or Fulfill)")
async def update_order_status_v1(order_id: str, update_req: UpdateOrderStatusRequest):
    """
    RESTful endpoint for modifying order state (cancellation or fulfillment).
    - Status **cancelled**: Cancels a pending order and updates cancellation metrics.
    - Status **fulfilled**: Marks a pending order as fulfilled.
    - Prevents invalid transitions with HTTP 409 Conflict.
    """
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order '{order_id}' was not found.")

    target_status = update_req.status

    if target_status == "cancelled":
        if order["status"] == "cancelled":
            raise HTTPException(status_code=409, detail=f"Order '{order_id}' is already cancelled.")
        if order["status"] == "fulfilled":
            raise HTTPException(status_code=409, detail=f"Order '{order_id}' cannot be cancelled because it has already been fulfilled.")

        order["status"] = "cancelled"
        order["cancellation_reason"] = update_req.reason
        ORDERS_CANCELLED_TOTAL.labels(reason=update_req.reason).inc()  # Counter
        PENDING_ORDERS_GAUGE.dec()                                      # Gauge

        logger.info(
            "order cancelled",
            extra={"extra_fields": {"order_id": order_id, "reason": update_req.reason}},
        )
        return {"order_id": order_id, "status": "cancelled", "reason": update_req.reason}

    elif target_status == "fulfilled":
        if order["status"] == "fulfilled":
            raise HTTPException(status_code=409, detail=f"Order '{order_id}' is already fulfilled.")
        if order["status"] == "cancelled":
            raise HTTPException(status_code=409, detail=f"Order '{order_id}' cannot be fulfilled because it has been cancelled.")

        order["status"] = "fulfilled"
        PENDING_ORDERS_GAUGE.dec()  # Gauge decrement

        logger.info(
            "order fulfilled",
            extra={"extra_fields": {"order_id": order_id}},
        )
        return {"order_id": order_id, "status": "fulfilled"}


# Backward compatibility aliases
@app.get("/api/orders", include_in_schema=False)
async def get_orders_legacy():
    return await get_all_orders_v1()


@app.post("/orders", include_in_schema=False)
async def place_order_legacy(order_req: OrderRequest, request: Request, response: Response):
    return await place_order_v1(order_req, request, response)


@app.post("/orders/{order_id}/cancel", include_in_schema=False)
async def cancel_order_legacy(order_id: str, cancel_req: CancelOrderRequest):
    return await update_order_status_v1(order_id, UpdateOrderStatusRequest(status="cancelled", reason=cancel_req.reason))


@app.post("/orders/{order_id}/fulfill", include_in_schema=False)
async def fulfill_order_legacy(order_id: str):
    return await update_order_status_v1(order_id, UpdateOrderStatusRequest(status="fulfilled"))


# --------------------------------------------------------------------------
# Metrics & Health Endpoints (Unchanged)
# --------------------------------------------------------------------------
@app.get("/metrics", tags=["Observability"], summary="Prometheus scrape target")
async def metrics():
    """Prometheus scrape target."""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health", tags=["Observability"], summary="Service health check")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}


# --------------------------------------------------------------------------
# Part E & Fault Injection Endpoints
# --------------------------------------------------------------------------
@app.post("/admin/fault", tags=["Admin & Observability"], summary="Configure fault injection")
async def set_fault(config: FaultConfigRequest):
    """Configure artificial delay, error rate, or specific status codes (e.g. 503)."""
    FAULT_CONFIG["delay_ms"] = config.delay_ms
    FAULT_CONFIG["error_rate"] = config.error_rate
    FAULT_CONFIG["status_code"] = config.status_code
    logger.warning(
        "fault configuration updated",
        extra={"extra_fields": {"fault_config": FAULT_CONFIG}},
    )
    return {"status": "updated", "fault_config": FAULT_CONFIG}


@app.get("/admin/cardinality-test", tags=["Admin & Observability"], summary="Cardinality explosion test")
async def cardinality_test(req_id: Optional[str] = None):
    """Endpoint to demonstrate cardinality explosion by adding request_id as a label."""
    target_id = req_id or str(uuid.uuid4())
    CARDINALITY_TEST_COUNTER.labels(request_id=target_id).inc()
    return {"message": "cardinality metric incremented", "request_id": target_id}


@app.post("/admin/reset-limits", tags=["Admin & Observability"], summary="Reset in-memory rate limits & idempotency cache")
async def reset_limits():
    """Admin endpoint to reset rate limits and idempotency cache for test isolation."""
    ORDER_RATE_LIMITER.reset()
    IDEMPOTENCY_STORE.clear()
    return {"status": "reset", "rate_limiter": "cleared", "idempotency_store": "cleared"}
