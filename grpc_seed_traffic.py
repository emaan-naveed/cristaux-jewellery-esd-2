"""
Cristaux Jewellery - Part C: repeatable gRPC traffic generator.

Populates the gRPC Prometheus panels (grpc_calls_total, duration histogram,
in-flight gauge) with a bounded mix of success and failure calls so the
Grafana dashboard has data to display. No browser needed.

Bounded status mix it produces:
  - CancelOrder OK               (cancel a freshly-seeded pending order)
  - CancelOrder NOT_FOUND        (cancel a non-existent order id)
  - CancelOrder FAILED_PRECONDITION (re-cancel an already-cancelled order)
  - GetOrder  OK                 (read an existing order)
  - GetOrder  NOT_FOUND          (read a non-existent order id)

Usage:
    # requires the gRPC server running (py -3 grpc_server.py)
    py -3 grpc_seed_traffic.py                # ~20 rounds, default host/deadline
    py -3 grpc_seed_traffic.py --rounds 40 --host 127.0.0.1:50051
"""

import argparse
import time
import uuid

import grpc

from proto import order_service_pb2, order_service_pb2_grpc

# Seed orders straight into the shared SQLite source of truth so the script
# is self-contained and does not depend on the REST API being up.
from app.orders_repository import create_order


def _seed_pending_order() -> str:
    order_id = f"ord-seed-{uuid.uuid4().hex[:6]}"
    create_order(
        order_id=order_id,
        customer_email="seed@cristaux.com",
        items=[{"id": "p1", "name": "Minimalist Silver Band Ring", "price": 1499.0}],
        total_amount=1499.0,
        status="pending",
    )
    return order_id


def run(rounds: int, host: str, deadline: float, sleep_s: float):
    print("=" * 70)
    print(" CRISTAUX JEWELLERY - Part C gRPC repeatable traffic generator")
    print(f" Target: {host} | rounds: {rounds} | deadline: {deadline}s | sleep: {sleep_s}s")
    print("=" * 70)

    counts = {"OK": 0, "NOT_FOUND": 0, "FAILED_PRECONDITION": 0}

    channel = grpc.insecure_channel(host)
    stub = order_service_pb2_grpc.OrderServiceStub(channel)

    for i in range(1, rounds + 1):
        trace = f"seed-{i}-{uuid.uuid4().hex[:8]}"
        metadata = (("x-request-id", trace),)

        # 1) SUCCESS: cancel a freshly-seeded pending order (OK)
        ok_order = _seed_pending_order()
        try:
            stub.CancelOrder(
                order_service_pb2.CancelOrderRequest(order_id=ok_order, reason="seed_cancel"),
                timeout=deadline, metadata=metadata,
            )
            counts["OK"] += 1
        except grpc.RpcError as e:
            counts[e.code().name] = counts.get(e.code().name, 0) + 1

        # 2) FAILURE: cancel a non-existent order (NOT_FOUND)
        try:
            stub.CancelOrder(
                order_service_pb2.CancelOrderRequest(order_id="ord-ghost-99999999", reason="seed_not_found"),
                timeout=deadline, metadata=metadata,
            )
        except grpc.RpcError as e:
            counts[e.code().name] = counts.get(e.code().name, 0) + 1

        # 3) FAILURE: re-cancel the order we just cancelled (FAILED_PRECONDITION)
        try:
            stub.CancelOrder(
                order_service_pb2.CancelOrderRequest(order_id=ok_order, reason="seed_re_cancel"),
                timeout=deadline, metadata=metadata,
            )
        except grpc.RpcError as e:
            counts[e.code().name] = counts.get(e.code().name, 0) + 1

        # 4) GetOrder OK on the seeded order before it is cancelled, then NOT_FOUND
        read_order = _seed_pending_order()
        try:
            stub.GetOrder(
                order_service_pb2.GetOrderRequest(order_id=read_order),
                timeout=deadline, metadata=metadata,
            )  # OK
            counts["OK"] += 1
        except grpc.RpcError as e:
            counts[e.code().name] = counts.get(e.code().name, 0) + 1

        try:
            stub.GetOrder(
                order_service_pb2.GetOrderRequest(order_id="ord-ghost-99999999"),
                timeout=deadline, metadata=metadata,
            )
        except grpc.RpcError as e:
            counts[e.code().name] = counts.get(e.code().name, 0) + 1

        if i % 5 == 0:
            print(f"  round {i}/{rounds} done | running totals: {counts}")
        time.sleep(sleep_s)

    channel.close()
    print("\n" + "=" * 70)
    print(" gRPC traffic generation complete. Status counts:")
    for status, n in counts.items():
        print(f"   {status:22s} {n}")
    print(" Panels for grpc_calls_total / duration / in-flight now have data.")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Part C gRPC repeatable traffic generator")
    parser.add_argument("--rounds", type=int, default=20, help="number of rounds (each = 5 RPCs)")
    parser.add_argument("--host", type=str, default="127.0.0.1:50051", help="gRPC host:port")
    parser.add_argument("--deadline", type=float, default=3.0, help="per-RPC deadline (s)")
    parser.add_argument("--sleep", type=float, default=0.2, help="sleep between rounds (s)")
    args = parser.parse_args()
    run(args.rounds, args.host, args.deadline, args.sleep)
