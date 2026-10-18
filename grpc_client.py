"""
Cristaux Jewellery - Standalone gRPC Python Client.

Calls the gRPC OrderService directly over HTTP/2 without browser interaction.
Features:
1. Accepts input parameters (order_id, reason, deadline).
2. Sets client-side deadline (timeout).
3. Transmits 'x-request-id' metadata for trace correlation.
4. Reports detailed results, gRPC status codes, and error details.
"""

import argparse
import sys
import time
import uuid

import grpc

# Import generated protobuf stubs
from proto import order_service_pb2, order_service_pb2_grpc

DEFAULT_HOST = "127.0.0.1:50051"
DEFAULT_DEADLINE = 3.0  # seconds


def cancel_order_rpc(
    order_id: str,
    reason: str = "customer_request",
    host: str = DEFAULT_HOST,
    deadline: float = DEFAULT_DEADLINE,
    request_id: str = None,
) -> bool:
    """
    Invoke CancelOrder RPC on gRPC OrderService with deadline and tracing metadata.
    """
    req_id = request_id or str(uuid.uuid4())
    print("\n" + "=" * 60)
    print(f" gRPC CLIENT INVOCATION: CancelOrder")
    print(f" Target Server:  {host}")
    print(f" Order ID:       {order_id}")
    print(f" Reason:         {reason}")
    print(f" Deadline:       {deadline}s")
    print(f" Trace ID:       {req_id}")
    print("=" * 60)

    start_time = time.perf_counter()

    try:
        with grpc.insecure_channel(host) as channel:
            stub = order_service_pb2_grpc.OrderServiceStub(channel)
            request = order_service_pb2.CancelOrderRequest(
                order_id=order_id, reason=reason
            )

            # Metadata passed across gRPC boundary for distributed trace correlation
            metadata = (("x-request-id", req_id),)

            # Direct unary RPC call with client-side deadline
            response = stub.CancelOrder(request, timeout=deadline, metadata=metadata)
            duration_ms = (time.perf_counter() - start_time) * 1000

            print("\n>>> RPC SUCCESSFUL <<<")
            print(f"  Status Code:   OK (0)")
            print(f"  Order ID:      {response.order_id}")
            print(f"  Order Status:  {response.status}")
            print(f"  Reason:        {response.reason}")
            print(f"  Updated At:    {response.updated_at}")
            print(f"  Server Msg:    {response.message}")
            print(f"  Round-Trip:    {duration_ms:.2f} ms")
            return True

    except grpc.RpcError as rpc_error:
        duration_ms = (time.perf_counter() - start_time) * 1000
        status_code = rpc_error.code()
        details = rpc_error.details()

        print("\n>>> RPC FAILED <<<")
        print(f"  gRPC Status:   {status_code.name} ({status_code.value[0]})")
        print(f"  Error Details: {details}")
        print(f"  Round-Trip:    {duration_ms:.2f} ms")

        if status_code == grpc.StatusCode.NOT_FOUND:
            print("  [Diagnosis]: The requested order does not exist in the database.")
        elif status_code == grpc.StatusCode.FAILED_PRECONDITION:
            print("  [Diagnosis]: Order state conflict (order is already cancelled or fulfilled).")
        elif status_code == grpc.StatusCode.DEADLINE_EXCEEDED:
            print(f"  [Diagnosis]: Server failed to respond within the {deadline}s deadline.")
        elif status_code == grpc.StatusCode.UNAVAILABLE:
            print(f"  [Diagnosis]: Could not connect to gRPC server at {host}. Is it running?")

        return False


def get_order_rpc(order_id: str, host: str = DEFAULT_HOST, deadline: float = DEFAULT_DEADLINE):
    """Retrieve order details via GetOrder RPC."""
    req_id = str(uuid.uuid4())
    try:
        with grpc.insecure_channel(host) as channel:
            stub = order_service_pb2_grpc.OrderServiceStub(channel)
            response = stub.GetOrder(
                order_service_pb2.GetOrderRequest(order_id=order_id),
                timeout=deadline,
                metadata=(("x-request-id", req_id),),
            )
            print(f"\nOrder: {response.order_id} | Customer: {response.customer_email} | Status: {response.status} | Total: PKR {response.total_amount}")
            return response
    except grpc.RpcError as e:
        print(f"\nGetOrder RPC Error: {e.code().name} - {e.details()}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Cristaux Jewellery gRPC Client")
    parser.add_argument("--order-id", type=str, help="Order ID to cancel")
    parser.add_argument("--reason", type=str, default="client_cancellation", help="Cancellation reason")
    parser.add_argument("--deadline", type=float, default=DEFAULT_DEADLINE, help="Client RPC deadline in seconds")
    parser.add_argument("--host", type=str, default=DEFAULT_HOST, help="gRPC host:port")
    parser.add_argument("--get", action="store_true", help="Retrieve order details instead of cancelling")

    args = parser.parse_args()

    if args.order_id:
        if args.get:
            get_order_rpc(args.order_id, args.host, args.deadline)
        else:
            cancel_order_rpc(args.order_id, args.reason, args.host, args.deadline)
    else:
        # Interactive prompt if no CLI flags passed
        print("=" * 60)
        print(" Cristaux Jewellery Interactive gRPC Client")
        print("=" * 60)
        oid = input("Enter Order ID to cancel (e.g. ord-12345678): ").strip()
        if not oid:
            print("Order ID required. Exiting.")
            sys.exit(1)
        reason = input("Enter cancellation reason [customer_changed_mind]: ").strip() or "customer_changed_mind"
        cancel_order_rpc(oid, reason, args.host, args.deadline)


if __name__ == "__main__":
    main()
