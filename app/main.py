"""
Cristaux Jewellery - Luxury E-Commerce Application with Observability.

Part A: E-Commerce Store Frontend & APIs (Products, Cart, Orders)
Part B: Metrics (Counter, Gauge, Histogram, Summary)
Part C: Structured JSON Logging (with x-request-id)
Part E: Fault Injection & Cardinality Explosion endpoints
"""

import json
import logging
import sys
import time
import uuid
from typing import Dict, Optional, List
from pydantic import BaseModel

from fastapi import FastAPI, Request, HTTPException, Query, Response
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
    title="Cristaux Jewellery Store",
    description="Luxury Jewellery E-Commerce Store with Prometheus Metrics & Filebeat JSON Logging",
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

# Fault Injection State (Part E1)
FAULT_CONFIG = {
    "delay_ms": 0.0,
    "error_rate": 0.0  # 0.0 to 1.0
}


# --------------------------------------------------------------------------
# Middleware: Request ID, Logging & Duration Histogram
# --------------------------------------------------------------------------
@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = time.perf_counter()

    # Fault injection: delay (Part E1)
    if FAULT_CONFIG["delay_ms"] > 0:
        time.sleep(FAULT_CONFIG["delay_ms"] / 1000.0)

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
# Domain API Models
# --------------------------------------------------------------------------
class AddToCartRequest(BaseModel):
    cart_id: str
    product_id: str

class OrderRequest(BaseModel):
    cart_id: str
    customer_email: str

class CancelOrderRequest(BaseModel):
    reason: str = "customer_changed_mind"

class FaultConfigRequest(BaseModel):
    delay_ms: float = 0.0
    error_rate: float = 0.0


# --------------------------------------------------------------------------
# Interactive UI Endpoint (Root Homepage)
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
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
                    <p style="color: var(--text-muted); font-size: 0.9rem;">Designed with timeless artistry and monitored with high-performance real-time telemetry.</p>
                </div>
            </div>
        </div>

        <footer>
            <p>&copy; 2026 Cristaux Jewellery Store. Enterprise Software Development Assignment 1.</p>
        </footer>

        <script>
            async function fetchAllOrders() {
                try {
                    const res = await fetch('/api/orders');
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
                
                // 1. Add to cart
                await fetch('/cart', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({cart_id: cartId, product_id: productId})
                });
                
                // 2. Checkout order
                const res = await fetch('/orders', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({cart_id: cartId, customer_email: 'vip@cristaux.com'})
                });
                
                const data = await res.json();
                await fetchAllOrders();
                alert('Order Placed Successfully! Order ID: ' + data.order_id);
            }

            async function cancelOrder(orderId) {
                const res = await fetch('/orders/' + orderId + '/cancel', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({reason: 'customer_cancelled_via_ui'})
                });
                
                await fetchAllOrders();
                alert('Order ' + orderId + ' has been cancelled.');
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
# Endpoints (Part A & B)
# --------------------------------------------------------------------------
@app.get("/api/orders")
async def get_all_orders():
    """Retrieve all placed orders for UI display and tracking."""
    return {"orders": list(ORDERS.values())}


@app.get("/products")
async def get_products(category: Optional[str] = None):
    """List available jewellery catalog."""
    if category:
        filtered = [p for p in PRODUCTS if p["category"] == category]
        return {"products": filtered}
    return {"products": PRODUCTS}


@app.post("/cart")
async def add_to_cart(item: AddToCartRequest):
    """Add item to shopping cart."""
    product = next((p for p in PRODUCTS if p["id"] == item.product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if item.cart_id not in CARTS:
        CARTS[item.cart_id] = []
        ACTIVE_CARTS_GAUGE.inc()  # Gauge increment

    CARTS[item.cart_id].append(product)
    logger.info(
        "item added to cart",
        extra={
            "extra_fields": {
                "cart_id": item.cart_id,
                "product_id": item.product_id,
                "item_name": product["name"],
            }
        },
    )
    return {"cart_id": item.cart_id, "items": CARTS[item.cart_id]}


@app.delete("/cart/{cart_id}")
async def clear_cart(cart_id: str):
    """Clear shopping cart."""
    if cart_id in CARTS:
        del CARTS[cart_id]
        ACTIVE_CARTS_GAUGE.dec()  # Gauge decrement
    return {"status": "cleared", "cart_id": cart_id}


@app.post("/orders")
async def place_order(order_req: OrderRequest):
    """Place an order from an active shopping cart."""
    cart_items = CARTS.get(order_req.cart_id)
    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty or does not exist")

    # Summary metric: time order creation execution
    start_time = time.perf_counter()

    order_id = f"ord-{uuid.uuid4().hex[:8]}"
    total_amount = sum(item["price"] for item in cart_items)
    main_category = cart_items[0]["category"]

    order = {
        "order_id": order_id,
        "customer_email": order_req.customer_email,
        "items": cart_items,
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
            }
        },
    )

    return order


@app.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, cancel_req: CancelOrderRequest):
    """Cancel a pending order."""
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order["status"] == "cancelled":
        return {"status": "already_cancelled"}

    order["status"] = "cancelled"
    ORDERS_CANCELLED_TOTAL.labels(reason=cancel_req.reason).inc()  # Counter
    PENDING_ORDERS_GAUGE.dec()                                      # Gauge

    logger.info(
        "order cancelled",
        extra={
            "extra_fields": {
                "order_id": order_id,
                "reason": cancel_req.reason,
            }
        },
    )
    return {"order_id": order_id, "status": "cancelled"}


@app.post("/orders/{order_id}/fulfill")
async def fulfill_order(order_id: str):
    """Fulfill a pending order."""
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order["status"] == "fulfilled":
        return {"status": "already_fulfilled"}

    order["status"] = "fulfilled"
    PENDING_ORDERS_GAUGE.dec()  # Gauge decrement

    logger.info(
        "order fulfilled",
        extra={"extra_fields": {"order_id": order_id}},
    )
    return {"order_id": order_id, "status": "fulfilled"}


# --------------------------------------------------------------------------
# Metrics Endpoint for Prometheus
# --------------------------------------------------------------------------
@app.get("/metrics")
async def metrics():
    """Prometheus scrape target."""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}


# --------------------------------------------------------------------------
# Part E: Experiments Support Endpoints
# --------------------------------------------------------------------------
@app.post("/admin/fault")
async def set_fault(config: FaultConfigRequest):
    """Configure artificial delay or errors (Part E1 - Reproduce a problem)."""
    FAULT_CONFIG["delay_ms"] = config.delay_ms
    FAULT_CONFIG["error_rate"] = config.error_rate
    logger.warning(
        "fault configuration updated",
        extra={"extra_fields": {"fault_config": FAULT_CONFIG}},
    )
    return {"status": "updated", "fault_config": FAULT_CONFIG}


@app.get("/admin/cardinality-test")
async def cardinality_test(req_id: Optional[str] = None):
    """Endpoint to demonstrate cardinality explosion by adding request_id as a label (Part E2)."""
    target_id = req_id or str(uuid.uuid4())
    CARDINALITY_TEST_COUNTER.labels(request_id=target_id).inc()
    return {"message": "cardinality metric incremented", "request_id": target_id}
