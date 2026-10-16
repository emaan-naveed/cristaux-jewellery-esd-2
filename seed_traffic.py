import time
import urllib.request
import json
import random
import uuid

BASE_URL = "http://localhost:8000"

def get(url):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"GET {url} error: {e}")
        return None

def post(url, data, headers=None):
    try:
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        json_data = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=json_data, headers=req_headers, method="POST")
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"POST {url} error: {e}")
        return None

def patch(url, data):
    try:
        json_data = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=json_data, headers={"Content-Type": "application/json"}, method="PATCH")
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"PATCH {url} error: {e}")
        return None

def run_simulation(duration_seconds=30):
    print(f"Starting Cristaux Jewellery RESTful traffic simulation for {duration_seconds} seconds...")
    start = time.time()
    products = get(f"{BASE_URL}/api/v1/products")
    product_list = products.get("products", []) if products else []
    
    if not product_list:
        print("Failed to fetch products. Is the server running?")
        return

    orders_placed = []
    
    while time.time() - start < duration_seconds:
        # 1. Browse products (RESTful v1)
        get(f"{BASE_URL}/api/v1/products")
        time.sleep(0.1)

        # 2. Add item to cart (RESTful v1)
        cart_id = f"cart-{random.randint(100, 999)}"
        chosen_product = random.choice(product_list)
        post(f"{BASE_URL}/api/v1/cart/items", {
            "cart_id": cart_id,
            "product_id": chosen_product["id"],
            "quantity": 1
        })
        time.sleep(0.1)

        # 3. Place order with Idempotency-Key
        idempotency_key = f"traffic-sim-{uuid.uuid4()}"
        order = post(
            f"{BASE_URL}/api/v1/orders",
            {
                "cart_id": cart_id,
                "customer_email": f"customer{random.randint(1, 50)}@example.com"
            },
            headers={"Idempotency-Key": idempotency_key}
        )
        
        if order and "order_id" in order:
            orders_placed.append(order["order_id"])

        time.sleep(0.2)

        # 4. Occasionally cancel or fulfill orders via RESTful PATCH
        if len(orders_placed) > 3 and random.random() < 0.3:
            target_order = orders_placed.pop(0)
            if random.random() < 0.5:
                patch(f"{BASE_URL}/api/v1/orders/{target_order}", {
                    "status": "cancelled",
                    "reason": "customer_changed_mind"
                })
            else:
                patch(f"{BASE_URL}/api/v1/orders/{target_order}", {
                    "status": "fulfilled",
                    "reason": "standard_delivery"
                })

    print(f"Simulation completed! Placed {len(orders_placed)} active orders.")

if __name__ == "__main__":
    run_simulation(30)
