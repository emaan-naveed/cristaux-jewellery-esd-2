"""
Cristaux Jewellery - Resilient Python Caller Service.

Acts as an external client service invoking the Cristaux Jewellery Orders API.
Demonstrates:
1. Request Timeout (1.5s)
2. Safe Retries with Exponential Backoff (guaranteed safe by Idempotency-Key)
3. Three-State Circuit Breaker (CLOSED -> OPEN -> HALF-OPEN -> CLOSED)
"""

import time
import uuid
import requests

BASE_URL = "http://127.0.0.1:8000"
session = requests.Session()

# Resilience Configuration Settings
REQUEST_TIMEOUT = 1.5          # Request timeout in seconds
MAX_RETRIES = 3                # Retry limit for transient errors
INITIAL_BACKOFF = 0.5          # Initial retry backoff in seconds
BACKOFF_FACTOR = 2.0           # Exponential multiplier
BREAKER_FAILURE_THRESHOLD = 3   # Consecutive failures before tripping to OPEN
BREAKER_RECOVERY_TIME = 4.0     # Cooldown before testing recovery in HALF-OPEN


class CircuitBreakerOpenException(Exception):
    """Raised when call is fast-failed locally because circuit breaker is OPEN."""
    pass


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_time: float = 4.0):
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self.state = "CLOSED"  # CLOSED, OPEN, HALF-OPEN
        self.consecutive_failures = 0
        self.last_failure_time = 0.0

    def before_call(self):
        now = time.time()
        if self.state == "OPEN":
            elapsed = now - self.last_failure_time
            if elapsed >= self.recovery_time:
                self.state = "HALF-OPEN"
                print(f"  [CircuitBreaker] Recovery cooldown elapsed ({elapsed:.2f}s >= {self.recovery_time}s).")
                print(f"  [CircuitBreaker] State transitioned: OPEN -> HALF-OPEN (allowing 1 canary trial request).")
            else:
                remaining = self.recovery_time - elapsed
                raise CircuitBreakerOpenException(
                    f"Circuit breaker is OPEN ({remaining:.1f}s cooldown remaining). Call blocked locally."
                )

    def on_success(self):
        prev = self.state
        self.state = "CLOSED"
        self.consecutive_failures = 0
        if prev in ("OPEN", "HALF-OPEN"):
            print(f"  [CircuitBreaker] Trial request SUCCEEDED! State transitioned: {prev} -> CLOSED (Fully Recovered).")

    def on_failure(self):
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        if self.state == "HALF-OPEN":
            self.state = "OPEN"
            print("  [CircuitBreaker] Trial request in HALF-OPEN failed! Tripped back to OPEN.")
        elif self.consecutive_failures >= self.failure_threshold:
            self.state = "OPEN"
            print(f"  [CircuitBreaker] Failure threshold reached ({self.consecutive_failures}/{self.failure_threshold})! State tripped: CLOSED -> OPEN (Blocking outgoing requests).")
        else:
            print(f"  [CircuitBreaker] Consecutive failures recorded: {self.consecutive_failures}/{self.failure_threshold} (Breaker remains CLOSED).")


breaker = CircuitBreaker(
    failure_threshold=BREAKER_FAILURE_THRESHOLD,
    recovery_time=BREAKER_RECOVERY_TIME,
)


def setup_cart(cart_id: str, product_id: str = "p1"):
    """Prepare a cart with a product item."""
    try:
        session.post(
            f"{BASE_URL}/api/v1/cart/items",
            json={"cart_id": cart_id, "product_id": product_id, "quantity": 1},
            timeout=2.0,
        )
    except Exception as e:
        print(f"    [Setup Error] Failed to seed cart {cart_id}: {e}")


def set_server_fault(delay_ms: float = 0.0, status_code: int = 0):
    """Trigger artificial fault injection on the server."""
    try:
        session.post(
            f"{BASE_URL}/admin/fault",
            json={"delay_ms": delay_ms, "status_code": status_code, "error_rate": 0.0},
            timeout=2.0,
        )
    except Exception as e:
        print(f"    [Fault Config Error]: {e}")


def make_resilient_order_call(call_label: str, cart_id: str, idempotency_key: str):
    """
    Execute order request with timeout, safe retries + backoff, and circuit breaker.
    """
    print(f"\n=======================================================")
    print(f">>> {call_label} (Breaker State: {breaker.state})")
    print(f"=======================================================")

    # 1. Circuit breaker guard
    try:
        breaker.before_call()
    except CircuitBreakerOpenException as exc:
        print(f"  [FAST FAIL] {exc}")
        print("  --> Request ABORTED without network traffic.")
        return None

    # 2. Execution with limited retries and exponential backoff
    url = f"{BASE_URL}/api/v1/orders"
    payload = {"cart_id": cart_id, "customer_email": "caller_service@example.com"}
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency_key,
    }

    attempt = 0
    backoff = INITIAL_BACKOFF

    while attempt < MAX_RETRIES:
        attempt += 1
        print(f"  -> Attempt {attempt}/{MAX_RETRIES} to POST {url} (Timeout={REQUEST_TIMEOUT}s, Idempotency-Key={idempotency_key[:16]}...)")
        start_t = time.perf_counter()

        try:
            resp = session.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            duration = time.perf_counter() - start_t

            if resp.status_code == 201:
                data = resp.json()
                replay = resp.headers.get("Idempotent-Replay", "false")
                print(f"  <- SUCCESS [HTTP 201 Created] in {duration:.3f}s (Order ID: {data.get('order_id')}, Replay: {replay})")
                breaker.on_success()
                return data
            elif resp.status_code in (500, 502, 503, 504):
                print(f"  <- TRANSIENT FAILURE [HTTP {resp.status_code}] in {duration:.3f}s: {resp.text.strip()}")
            else:
                # Non-transient client error (e.g. 400 Bad Request, 422 Unprocessable)
                print(f"  <- NON-TRANSIENT ERROR [HTTP {resp.status_code}] in {duration:.3f}s: {resp.text.strip()}")
                breaker.on_failure()
                return None

        except requests.exceptions.Timeout:
            duration = time.perf_counter() - start_t
            print(f"  <- TIMEOUT [Exceeded {REQUEST_TIMEOUT}s limit] (Duration: {duration:.3f}s)")
        except requests.exceptions.RequestException as e:
            duration = time.perf_counter() - start_t
            print(f"  <- NETWORK ERROR ({type(e).__name__}) in {duration:.3f}s")

        # Backoff before next attempt
        if attempt < MAX_RETRIES:
            print(f"     [Retry Engine] Operation is protected with Idempotency-Key -> Safe to retry.")
            print(f"     [Backoff] Waiting {backoff:.2f}s before attempt {attempt + 1}...")
            time.sleep(backoff)
            backoff *= BACKOFF_FACTOR

    print(f"  [Failure] All {MAX_RETRIES} attempts exhausted without success.")
    breaker.on_failure()
    return None


def run_caller_suite():
    print("*" * 65)
    print(" CRISTAUX JEWELLERY CALLER SERVICE DEMONSTRATION")
    print(" Resilience Settings:")
    print(f"   • Timeout:                  {REQUEST_TIMEOUT}s")
    print(f"   • Retry Limit:              {MAX_RETRIES} attempts")
    print(f"   • Retry Backoff Strategy:   Exponential (Initial: {INITIAL_BACKOFF}s, Multiplier: {BACKOFF_FACTOR}x)")
    print(f"   • Circuit Breaker Settings: Threshold={BREAKER_FAILURE_THRESHOLD} failures, Recovery Cooldown={BREAKER_RECOVERY_TIME}s")
    print("*" * 65)

    # Reset any active faults on server
    set_server_fault(delay_ms=0, status_code=0)
    session.post(f"{BASE_URL}/admin/reset-limits")

    # -------------------------------------------------------------
    # PHASE 1: Normal Succeeding Calls (Breaker: CLOSED)
    # -------------------------------------------------------------
    print("\n>>> PHASE 1: Normal Succeeding Operations (Breaker: CLOSED) <<<")
    cart1 = f"cart-{uuid.uuid4().hex[:6]}"
    setup_cart(cart1)
    make_resilient_order_call("Call #1 (Healthy Checkout)", cart1, f"idem-key-{uuid.uuid4().hex[:8]}")

    cart2 = f"cart-{uuid.uuid4().hex[:6]}"
    setup_cart(cart2)
    make_resilient_order_call("Call #2 (Healthy Checkout)", cart2, f"idem-key-{uuid.uuid4().hex[:8]}")

    # -------------------------------------------------------------
    # PHASE 2: Transient Failures & Retries with Backoff
    # -------------------------------------------------------------
    print("\n>>> PHASE 2: Transient Server Outage Injected (503 Service Unavailable) <<<")
    print("Injecting HTTP 503 fault to trigger retry engine...")
    set_server_fault(status_code=503)

    # Call 3: Will retry 3 times with exponential backoff and then register failure #1
    cart3 = f"cart-{uuid.uuid4().hex[:6]}"
    setup_cart(cart3)
    make_resilient_order_call("Call #3 (Fault Injected - Transient 503)", cart3, f"idem-key-{uuid.uuid4().hex[:8]}")

    # Call 4: Will retry 3 times with backoff and register failure #2
    cart4 = f"cart-{uuid.uuid4().hex[:6]}"
    setup_cart(cart4)
    make_resilient_order_call("Call #4 (Fault Injected - Transient 503)", cart4, f"idem-key-{uuid.uuid4().hex[:8]}")

    # Call 5: Will retry 3 times with backoff and trip the circuit breaker (failure #3)
    cart5 = f"cart-{uuid.uuid4().hex[:6]}"
    setup_cart(cart5)
    make_resilient_order_call("Call #5 (Fault Injected - Trips Breaker)", cart5, f"idem-key-{uuid.uuid4().hex[:8]}")

    # -------------------------------------------------------------
    # PHASE 3: Blocking Calls While Circuit Breaker is OPEN
    # -------------------------------------------------------------
    print("\n>>> PHASE 3: Fast-Failing While Breaker is OPEN <<<")
    cart6 = f"cart-{uuid.uuid4().hex[:6]}"
    setup_cart(cart6)
    make_resilient_order_call("Call #6 (Fast-Fail while OPEN)", cart6, f"idem-key-{uuid.uuid4().hex[:8]}")

    cart7 = f"cart-{uuid.uuid4().hex[:6]}"
    setup_cart(cart7)
    make_resilient_order_call("Call #7 (Fast-Fail while OPEN)", cart7, f"idem-key-{uuid.uuid4().hex[:8]}")

    # -------------------------------------------------------------
    # PHASE 4: Recovery (Transition to HALF-OPEN then CLOSED)
    # -------------------------------------------------------------
    print("\n>>> PHASE 4: Server Healing & Breaker Recovery <<<")
    print("1. Clearing server fault (Server returns to 200 OK)...")
    set_server_fault(delay_ms=0, status_code=0)

    print(f"2. Waiting for recovery cooldown period ({BREAKER_RECOVERY_TIME}s)...")
    time.sleep(BREAKER_RECOVERY_TIME + 0.5)

    print("3. Sending canary trial request (Transitions Breaker to HALF-OPEN)...")
    cart8 = f"cart-{uuid.uuid4().hex[:6]}"
    setup_cart(cart8)
    make_resilient_order_call("Call #8 (Canary Trial Checkout)", cart8, f"idem-key-{uuid.uuid4().hex[:8]}")

    print("4. Verifying subsequent request in fully recovered CLOSED state...")
    cart9 = f"cart-{uuid.uuid4().hex[:6]}"
    setup_cart(cart9)
    make_resilient_order_call("Call #9 (Post-Recovery Healthy Checkout)", cart9, f"idem-key-{uuid.uuid4().hex[:8]}")

    print("\n" + "=" * 65)
    print(" CALLER SUITE DEMONSTRATION COMPLETE: ALL PHASES VERIFIED")
    print("=" * 65)


if __name__ == "__main__":
    run_caller_suite()
