"""
Dual Protocol Comparison Suite: HTTP REST vs. gRPC.

Validates the CancelOrder operation through both:
1. HTTP REST API (FastAPI) via PATCH /api/v1/orders/{order_id}
2. gRPC Service via OrderService.CancelOrder RPC

Demonstrates:
- Successful cancellation in both protocols.
- Failed cancellation (Not Found) in both protocols.
- Failed cancellation (State Conflict / Already Cancelled) in both protocols.
- Status code mapping and explanation.
- Cross-boundary trace correlation using 'x-request-id'.
"""

import time
import uuid
import requests
import grpc

from proto import order_service_pb2, order_service_pb2_grpc
from app.orders_repository import create_order, get_order

HTTP_BASE_URL = "http://127.0.0.1:8000"
GRPC_HOST = "127.0.0.1:50051"
session = requests.Session()


def setup_pending_order(prefix: str) -> str:
    """Seed a pending order in the shared SQLite source of truth."""
    order_id = f"ord-{prefix}-{uuid.uuid4().hex[:6]}"
    create_order(
        order_id=order_id,
        customer_email=f"client_{prefix}@cristaux.com",
        items=[{"id": "p1", "name": "Minimalist Silver Band Ring", "price": 1499.0}],
        total_amount=1499.0,
        status="pending",
    )
    return order_id


def run_dual_comparison():
    print("*" * 75)
    print(" CRISTAUX JEWELLERY: DUAL PROTOCOL COMPARISON SUITE (HTTP REST vs. gRPC)")
    print("*" * 75)

    # =========================================================================
    # SCENARIO 1: SUCCESSFUL CANCELLATION
    # =========================================================================
    print("\n" + "=" * 75)
    print(" SCENARIO 1: SUCCESSFUL CANCELLATION OF A PENDING ORDER")
    print("=" * 75)

    # 1A. HTTP REST Version
    http_order_id = setup_pending_order("http-succ")
    http_trace_id = f"trace-http-{uuid.uuid4().hex[:8]}"
    print(f"\n[1A. HTTP REST] Cancelling Order: {http_order_id}...")
    t0 = time.perf_counter()
    http_resp = session.patch(
        f"{HTTP_BASE_URL}/api/v1/orders/{http_order_id}",
        json={"status": "cancelled", "reason": "customer_changed_mind_via_http"},
        headers={"x-request-id": http_trace_id},
    )
    http_dur = (time.perf_counter() - t0) * 1000

    print(f"  HTTP Method/URL:  PATCH /api/v1/orders/{http_order_id}")
    print(f"  HTTP Status Code: {http_resp.status_code} OK")
    print(f"  Trace ID:         {http_resp.headers.get('x-request-id')}")
    print(f"  Response Body:    {http_resp.json()}")
    print(f"  Round-Trip Time:  {http_dur:.2f} ms")
    assert http_resp.status_code == 200, f"Expected 200, got {http_resp.status_code}"

    # 1B. gRPC Version
    grpc_order_id = setup_pending_order("grpc-succ")
    grpc_trace_id = f"trace-grpc-{uuid.uuid4().hex[:8]}"
    print(f"\n[1B. gRPC Service] Cancelling Order: {grpc_order_id}...")
    t0 = time.perf_counter()
    with grpc.insecure_channel(GRPC_HOST) as channel:
        stub = order_service_pb2_grpc.OrderServiceStub(channel)
        grpc_resp, call = stub.CancelOrder.with_call(
            order_service_pb2.CancelOrderRequest(
                order_id=grpc_order_id,
                reason="customer_changed_mind_via_grpc",
            ),
            timeout=3.0,
            metadata=(("x-request-id", grpc_trace_id),),
        )
    grpc_dur = (time.perf_counter() - t0) * 1000

    trailing_meta = dict(call.trailing_metadata())
    print(f"  RPC Invoked:      cristaux.orders.OrderService/CancelOrder")
    print(f"  gRPC Status Code: OK (0)")
    print(f"  Trace ID:         {trailing_meta.get('x-request-id')}")
    print(f"  Response Message: order_id='{grpc_resp.order_id}', status='{grpc_resp.status}', reason='{grpc_resp.reason}'")
    print(f"  Round-Trip Time:  {grpc_dur:.2f} ms")
    assert grpc_resp.status == "cancelled"

    # Verify both orders in the shared database
    db_http = get_order(http_order_id)
    db_grpc = get_order(grpc_order_id)
    assert db_http["status"] == "cancelled"
    assert db_grpc["status"] == "cancelled"
    print("\n>>> VERIFICATION: Both orders verified as 'cancelled' in shared SQLite database.")

    # =========================================================================
    # SCENARIO 2: FAILED REQUEST — ORDER NOT FOUND
    # =========================================================================
    print("\n" + "=" * 75)
    print(" SCENARIO 2: FAILED REQUEST — NON-EXISTENT ORDER (404 vs. NOT_FOUND)")
    print("=" * 75)

    non_existent_id = "ord-ghost-99999999"

    # 2A. HTTP REST
    print(f"\n[2A. HTTP REST] Attempting to cancel non-existent order: {non_existent_id}...")
    http_resp_404 = session.patch(
        f"{HTTP_BASE_URL}/api/v1/orders/{non_existent_id}",
        json={"status": "cancelled", "reason": "testing_not_found"},
    )
    print(f"  HTTP Status Code: {http_resp_404.status_code} Not Found")
    print(f"  Standard Error:   {http_resp_404.json()}")
    assert http_resp_404.status_code == 404
    assert http_resp_404.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    # 2B. gRPC
    print(f"\n[2B. gRPC Service] Attempting to cancel non-existent order: {non_existent_id}...")
    try:
        with grpc.insecure_channel(GRPC_HOST) as channel:
            stub = order_service_pb2_grpc.OrderServiceStub(channel)
            stub.CancelOrder(
                order_service_pb2.CancelOrderRequest(order_id=non_existent_id, reason="testing_not_found"),
                timeout=3.0,
            )
        assert False, "Should have raised gRPC NOT_FOUND RpcError"
    except grpc.RpcError as e:
        print(f"  gRPC Status Code: {e.code().name} ({e.code().value[0]})")
        print(f"  gRPC Details:     {e.details()}")
        assert e.code() == grpc.StatusCode.NOT_FOUND

    # =========================================================================
    # SCENARIO 3: FAILED REQUEST — CONFLICT / ALREADY CANCELLED
    # =========================================================================
    print("\n" + "=" * 75)
    print(" SCENARIO 3: FAILED REQUEST — INVALID STATE TRANSITION (409 vs. FAILED_PRECONDITION)")
    print("=" * 75)

    # 3A. HTTP REST: Re-cancel already cancelled order
    print(f"\n[3A. HTTP REST] Attempting to cancel already cancelled order: {http_order_id}...")
    http_resp_409 = session.patch(
        f"{HTTP_BASE_URL}/api/v1/orders/{http_order_id}",
        json={"status": "cancelled", "reason": "second_cancel_attempt"},
    )
    print(f"  HTTP Status Code: {http_resp_409.status_code} Conflict")
    print(f"  Standard Error:   {http_resp_409.json()}")
    assert http_resp_409.status_code == 409
    assert http_resp_409.json()["error"]["code"] == "CONFLICT"

    # 3B. gRPC: Re-cancel already cancelled order
    print(f"\n[3B. gRPC Service] Attempting to cancel already cancelled order: {grpc_order_id}...")
    try:
        with grpc.insecure_channel(GRPC_HOST) as channel:
            stub = order_service_pb2_grpc.OrderServiceStub(channel)
            stub.CancelOrder(
                order_service_pb2.CancelOrderRequest(order_id=grpc_order_id, reason="second_cancel_attempt"),
                timeout=3.0,
            )
        assert False, "Should have raised gRPC FAILED_PRECONDITION RpcError"
    except grpc.RpcError as e:
        print(f"  gRPC Status Code: {e.code().name} ({e.code().value[0]})")
        print(f"  gRPC Details:     {e.details()}")
        assert e.code() == grpc.StatusCode.FAILED_PRECONDITION

    # =========================================================================
    # STATUS CODE COMPARISON TABLE
    # =========================================================================
    print("\n" + "=" * 75)
    print(" PROTOCOL STATUS CODE MAPPING & EXPLANATION")
    print("=" * 75)
    print("+" + "-" * 23 + "+" + "-" * 14 + "+" + "-" * 25 + "+" + "-" * 56 + "+")
    print("| Scenario              | HTTP Status  | gRPC Status Code        | Architectural Meaning & Explanation                    |")
    print("+" + "-" * 23 + "+" + "-" * 14 + "+" + "-" * 25 + "+" + "-" * 56 + "+")
    print("| Successful Cancel     | 200 OK       | OK (0)                  | Operation fulfilled successfully; state modified.       |")
    print("| Missing Order         | 404 Not Found| NOT_FOUND (5)           | Target order_id does not exist in source of truth.     |")
    print("| Already Cancelled     | 409 Conflict | FAILED_PRECONDITION (9) | Rejected because order is not in valid 'pending' state.|")
    print("| Request Timeout       | 504 / 408    | DEADLINE_EXCEEDED (4)   | Processing exceeded client-configured timeout window.  |")
    print("+" + "-" * 23 + "+" + "-" * 14 + "+" + "-" * 25 + "+" + "-" * 56 + "+")
    print(">>> DUAL PROTOCOL VERIFICATION COMPLETE: ALL ASSERTIONS PASSED! <<<")


if __name__ == "__main__":
    run_dual_comparison()
