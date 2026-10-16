"""
Automated Test Suite for Cristaux Jewellery Store API.

Tests:
1. Valid Request (Add to cart & Checkout -> 201 Created with Location header)
2. Invalid Input (Bad cart, malformed email, negative quantities -> 400/422 with consistent error schema)
3. Repeated Request / Idempotency (Safe repeats -> 201 with Idempotent-Replay: true, no duplicate records)
4. Rate Limiting (Burst of 6 requests -> 6th receives 429 Too Many Requests with Retry-After header)
"""

import time
import uuid
import requests

BASE_URL = "http://127.0.0.1:8000"
session = requests.Session()


def test_valid_request():
    print("\n--- TEST 1: Valid Request ---")
    cart_id = f"test-cart-{uuid.uuid4().hex[:6]}"
    
    # 1. Add item to cart
    add_resp = session.post(
        f"{BASE_URL}/api/v1/cart/items",
        json={"cart_id": cart_id, "product_id": "p1", "quantity": 2},
    )
    print(f"Add to cart status: {add_resp.status_code}")
    assert add_resp.status_code == 200, f"Expected 200, got {add_resp.status_code}"
    cart_data = add_resp.json()
    assert cart_data["item_count"] == 2
    print(f"Cart contents: {cart_data['item_count']} items, Total: PKR {cart_data['total_amount']}")

    # 2. Checkout order
    idem_key = f"key-{uuid.uuid4()}"
    order_resp = session.post(
        f"{BASE_URL}/api/v1/orders",
        json={"cart_id": cart_id, "customer_email": "royal.client@cristaux.com"},
        headers={"Idempotency-Key": idem_key},
    )
    print(f"Place order status: {order_resp.status_code}")
    assert order_resp.status_code == 201, f"Expected 201 Created, got {order_resp.status_code}"
    order_data = order_resp.json()
    order_id = order_data["order_id"]
    location = order_resp.headers.get("Location")
    print(f"Created Order ID: {order_id}")
    print(f"Location Header: {location}")
    print(f"Idempotent-Replay Header: {order_resp.headers.get('Idempotent-Replay')}")
    assert location == f"/api/v1/orders/{order_id}"
    assert order_data["status"] == "pending"
    print(">>> TEST 1 PASSED: Valid Request returned 201 Created with Location header.")
    return order_id


def test_invalid_input():
    print("\n--- TEST 2: Invalid Input Validation & Consistent Error Format ---")

    # 2a. Non-existent cart
    resp_empty = session.post(
        f"{BASE_URL}/api/v1/orders",
        json={"cart_id": "non-existent-cart-999", "customer_email": "test@example.com"},
    )
    print(f"Empty Cart Order Status: {resp_empty.status_code}")
    assert resp_empty.status_code == 400
    err_body = resp_empty.json()
    print("Standardized Error Format (Empty Cart):")
    print(err_body)
    assert "error" in err_body
    assert err_body["error"]["code"] == "BAD_REQUEST"
    assert "timestamp" in err_body["error"]

    # 2b. Malformed email address
    cart_id = f"test-cart-{uuid.uuid4().hex[:6]}"
    session.post(f"{BASE_URL}/api/v1/cart/items", json={"cart_id": cart_id, "product_id": "p2", "quantity": 1})
    resp_email = session.post(
        f"{BASE_URL}/api/v1/orders",
        json={"cart_id": cart_id, "customer_email": "invalid-email-without-domain"},
    )
    print(f"\nInvalid Email Status: {resp_email.status_code}")
    assert resp_email.status_code == 422
    err_body_email = resp_email.json()
    print("Standardized Error Format (Schema Validation):")
    print(err_body_email)
    assert err_body_email["error"]["code"] == "VALIDATION_ERROR"
    assert "customer_email" in str(err_body_email["error"]["details"])

    # 2c. Invalid Quantity (< 1)
    resp_qty = session.post(
        f"{BASE_URL}/api/v1/cart/items",
        json={"cart_id": cart_id, "product_id": "p2", "quantity": -3},
    )
    print(f"\nNegative Quantity Status: {resp_qty.status_code}")
    assert resp_qty.status_code == 422
    err_body_qty = resp_qty.json()
    assert err_body_qty["error"]["code"] == "VALIDATION_ERROR"

    print(">>> TEST 2 PASSED: Invalid inputs properly rejected with consistent error envelope.")


def test_repeated_request_idempotency():
    print("\n--- TEST 3: Idempotency (Safe Repeats) ---")
    session.post(f"{BASE_URL}/admin/reset-limits")

    cart_id = f"test-cart-{uuid.uuid4().hex[:6]}"
    session.post(f"{BASE_URL}/api/v1/cart/items", json={"cart_id": cart_id, "product_id": "p3", "quantity": 1})

    idempotency_key = f"unique-idempotency-{uuid.uuid4().hex}"

    # 1st Request
    print(f"Sending First Request with Idempotency-Key: {idempotency_key}")
    resp1 = session.post(
        f"{BASE_URL}/api/v1/orders",
        json={"cart_id": cart_id, "customer_email": "repeat.client@cristaux.com"},
        headers={"Idempotency-Key": idempotency_key},
    )
    assert resp1.status_code == 201
    order1 = resp1.json()
    replay_header1 = resp1.headers.get("Idempotent-Replay")
    print(f"1st Response Status: {resp1.status_code}, Order ID: {order1['order_id']}, Replay Header: {replay_header1}")
    assert replay_header1 == "false"

    # 2nd Repeated Request (Simulating network timeout retry)
    print(f"\nSending Second (REPEATED) Request with IDENTICAL Idempotency-Key...")
    resp2 = session.post(
        f"{BASE_URL}/api/v1/orders",
        json={"cart_id": cart_id, "customer_email": "repeat.client@cristaux.com"},
        headers={"Idempotency-Key": idempotency_key},
    )
    assert resp2.status_code == 201
    order2 = resp2.json()
    replay_header2 = resp2.headers.get("Idempotent-Replay")
    print(f"2nd Response Status: {resp2.status_code}, Order ID: {order2['order_id']}, Replay Header: {replay_header2}")
    assert replay_header2 == "true"
    assert order1["order_id"] == order2["order_id"], "Order IDs must match exactly!"

    # Verify no duplicate order in order listing
    all_orders = session.get(f"{BASE_URL}/api/v1/orders").json()["orders"]
    matching = [o for o in all_orders if o["order_id"] == order1["order_id"]]
    assert len(matching) == 1, f"Expected exactly 1 order in database, found {len(matching)}"
    print(f"Verified database: exactly 1 order exists for ID {order1['order_id']} (NO duplicates created).")

    print(">>> TEST 3 PASSED: Repeated request safely handled via Idempotency-Key.")


def test_rate_limiting():
    print("\n--- TEST 4: Rate Limiting & 429 Too Many Requests ---")
    session.post(f"{BASE_URL}/admin/reset-limits")

    limit = 5
    print(f"Testing Rate Limiter: Endpoint Limit = {limit} requests per 10-second window.")
    
    # Pre-create 6 carts so we can burst all 6 orders without intervening delays
    carts = []
    for i in range(1, 7):
        cid = f"rl-cart-{i}-{uuid.uuid4().hex[:4]}"
        session.post(f"{BASE_URL}/api/v1/cart/items", json={"cart_id": cid, "product_id": "p4", "quantity": 1})
        carts.append(cid)

    # Burst 6 order placements
    responses = []
    for i, cid in enumerate(carts, 1):
        resp = session.post(
            f"{BASE_URL}/api/v1/orders",
            json={"cart_id": cid, "customer_email": f"burst{i}@cristaux.com"},
            headers={"Idempotency-Key": f"rl-key-{i}-{uuid.uuid4().hex}"},
        )
        remaining = resp.headers.get("X-RateLimit-Remaining")
        retry_after = resp.headers.get("Retry-After")
        print(f"Request #{i}: Status={resp.status_code}, X-RateLimit-Remaining={remaining}, Retry-After={retry_after}")
        responses.append(resp)

    # First 5 should succeed (201 Created)
    for i in range(5):
        assert responses[i].status_code == 201, f"Expected 201 for request {i+1}, got {responses[i].status_code}"

    # 6th must receive 429 Too Many Requests
    r6 = responses[5]
    assert r6.status_code == 429, f"Expected 429 Too Many Requests for request 6, got {r6.status_code}"
    assert "Retry-After" in r6.headers, "Missing Retry-After header!"
    retry_after_val = r6.headers["Retry-After"]
    err = r6.json()
    print(f"\n429 Response Details:")
    print(f"Status Code:  429 Too Many Requests")
    print(f"Retry-After:  {retry_after_val} seconds")
    print(f"Error Body:   {err}")
    assert err["error"]["code"] == "RATE_LIMIT_EXCEEDED"

    print(">>> TEST 4 PASSED: Rate limit accepted 5 requests, rejected 6th with 429 & Retry-After header.")


def run_all_tests():
    print("=" * 65)
    print(" RUNNING CRISTAUX JEWELLERY REST ASSIGNMENT TEST SUITE")
    print("=" * 65)
    test_valid_request()
    test_invalid_input()
    test_repeated_request_idempotency()
    test_rate_limiting()
    print("\n" + "=" * 65)
    print(" ALL 4 TESTS PASSED SUCCESSFULLY! ")
    print("=" * 65)


if __name__ == "__main__":
    run_all_tests()
