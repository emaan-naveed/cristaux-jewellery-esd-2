import time
import urllib.request
import json
import random

BASE_URL = "http://localhost:8000"

def get(url):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"GET {url} error: {e}")
        return None

def post(url, data):
    try:
        json_data = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=json_data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"POST {url} error: {e}")
        return None

def run_simulation(duration_seconds=30):
    print(f"Starting Cristaux Jewellery traffic simulation for {duration_seconds} seconds...")
    start = time.time()
    products = get(f"{BASE_URL}/products")
    product_list = products.get("products", []) if products else []
    
    if not product_list:
        print("Failed to fetch products. Is the server running?")
        return

    orders_placed = []
    
    while time.time() - start < duration_seconds:
        # 1. Browse products
        get(f"{BASE_URL}/products")
        time.sleep(0.1)

        # 2. Add item to cart
        cart_id = f"cart-{random.randint(100, 999)}"
        chosen_product = random.choice(product_list)
        post(f"{BASE_URL}/cart", {"cart_id": cart_id, "product_id": chosen_product["id"]})
        time.sleep(0.1)

        # 3. Place order
        order = post(f"{BASE_URL}/orders", {
            "cart_id": cart_id,
            "customer_email": f"customer{random.randint(1, 50)}@example.com"
        })
        
        if order and "order_id" in order:
            orders_placed.append(order["order_id"])

        time.sleep(0.2)

        # 4. Occasionally cancel or fulfill orders
        if len(orders_placed) > 3 and random.random() < 0.3:
            target_order = orders_placed.pop(0)
            if random.random() < 0.5:
                post(f"{BASE_URL}/orders/{target_order}/cancel", {"reason": "customer_changed_mind"})
            else:
                post(f"{BASE_URL}/orders/{target_order}/fulfill", {})

    print(f"Simulation completed! Placed {len(orders_placed)} active orders.")

if __name__ == "__main__":
    run_simulation(30)
