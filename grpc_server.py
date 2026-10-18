"""
Cristaux Jewellery - Standalone gRPC Service Process.

Part B: gRPC Service implementation for Order lifecycle management.
- Exposes unary RPCs defined in proto/order_service.proto.
- Shares the same business rules and SQLite source of truth with the REST API.
- Implements trace correlation via metadata ('x-request-id') and structured JSON logging.
"""

import json
import logging
import sys
import time
import uuid
from concurrent import futures
from typing import Dict, Any

import grpc

# Import generated protobuf stubs
from proto import order_service_pb2, order_service_pb2_grpc

# Import shared domain repository (SAME source of truth and business rules)
from app.orders_repository import (
    cancel_order as db_cancel_order,
    get_order as db_get_order,
)

# --------------------------------------------------------------------------
# Structured JSON Logging Setup (Preserving Assignment 1 Logging Schema)
# --------------------------------------------------------------------------
SERVICE_NAME = "Cristaux Jewellery gRPC Service"


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


def extract_request_id(context: grpc.ServicerContext) -> str:
    """Extract 'x-request-id' from gRPC invocation metadata for cross-boundary tracing."""
    metadata = dict(context.invocation_metadata())
    return metadata.get("x-request-id") or str(uuid.uuid4())


# --------------------------------------------------------------------------
# gRPC Servicer Implementation
# --------------------------------------------------------------------------
class OrderServiceServicer(order_service_pb2_grpc.OrderServiceServicer):
    """
    Implements OrderService defined in order_service.proto.
    Directly executes shared business rules on SQLite persistence layer.
    """

    def CancelOrder(
        self,
        request: order_service_pb2.CancelOrderRequest,
        context: grpc.ServicerContext,
    ) -> order_service_pb2.CancelOrderResponse:
        started = time.perf_counter()
        request_id = extract_request_id(context)
        reason = request.reason.strip() if request.reason else "customer_request"

        logger.info(
            "gRPC CancelOrder request received",
            extra={
                "extra_fields": {
                    "request_id": request_id,
                    "rpc": "CancelOrder",
                    "order_id": request.order_id,
                    "reason": reason,
                }
            },
        )

        # Enforce shared domain business rules via repository
        ok, outcome, order = db_cancel_order(request.order_id, reason)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        if outcome == "NOT_FOUND":
            logger.warning(
                "gRPC CancelOrder failed: order not found",
                extra={
                    "extra_fields": {
                        "request_id": request_id,
                        "rpc": "CancelOrder",
                        "order_id": request.order_id,
                        "status_code": "NOT_FOUND",
                        "duration_ms": duration_ms,
                    }
                },
            )
            context.abort(
                grpc.StatusCode.NOT_FOUND,
                f"Order '{request.order_id}' was not found in the database.",
            )

        elif outcome == "ALREADY_CANCELLED":
            logger.warning(
                "gRPC CancelOrder failed: order already cancelled",
                extra={
                    "extra_fields": {
                        "request_id": request_id,
                        "rpc": "CancelOrder",
                        "order_id": request.order_id,
                        "status_code": "FAILED_PRECONDITION",
                        "duration_ms": duration_ms,
                    }
                },
            )
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                f"Order '{request.order_id}' is already in cancelled state.",
            )

        elif outcome == "ALREADY_FULFILLED":
            logger.warning(
                "gRPC CancelOrder failed: order already fulfilled",
                extra={
                    "extra_fields": {
                        "request_id": request_id,
                        "rpc": "CancelOrder",
                        "order_id": request.order_id,
                        "status_code": "FAILED_PRECONDITION",
                        "duration_ms": duration_ms,
                    }
                },
            )
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                f"Order '{request.order_id}' cannot be cancelled because it has already been fulfilled.",
            )

        # Success
        logger.info(
            "gRPC CancelOrder succeeded",
            extra={
                "extra_fields": {
                    "request_id": request_id,
                    "rpc": "CancelOrder",
                    "order_id": request.order_id,
                    "status_code": "OK",
                    "duration_ms": duration_ms,
                }
            },
        )

        # Send response trailing metadata with request_id for caller tracing
        context.set_trailing_metadata((("x-request-id", request_id),))

        return order_service_pb2.CancelOrderResponse(
            order_id=order["order_id"],
            status="cancelled",
            reason=order["cancellation_reason"] or reason,
            updated_at=time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(order["updated_at"])
            ),
            message="Order cancelled successfully via gRPC service.",
        )

    def GetOrder(
        self,
        request: order_service_pb2.GetOrderRequest,
        context: grpc.ServicerContext,
    ) -> order_service_pb2.GetOrderResponse:
        started = time.perf_counter()
        request_id = extract_request_id(context)

        order = db_get_order(request.order_id)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        if not order:
            logger.warning(
                "gRPC GetOrder failed: not found",
                extra={
                    "extra_fields": {
                        "request_id": request_id,
                        "rpc": "GetOrder",
                        "order_id": request.order_id,
                        "status_code": "NOT_FOUND",
                        "duration_ms": duration_ms,
                    }
                },
            )
            context.abort(
                grpc.StatusCode.NOT_FOUND,
                f"Order '{request.order_id}' not found.",
            )

        items_pb = [
            order_service_pb2.OrderItem(
                id=item.get("id", ""),
                name=item.get("name", ""),
                category=item.get("category", ""),
                price=float(item.get("price", 0.0)),
            )
            for item in order.get("items", [])
        ]

        context.set_trailing_metadata((("x-request-id", request_id),))

        return order_service_pb2.GetOrderResponse(
            order_id=order["order_id"],
            customer_email=order["customer_email"],
            total_amount=order["total_amount"],
            status=order["status"],
            cancellation_reason=order.get("cancellation_reason") or "",
            created_at=time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(order["created_at"])
            ),
            items=items_pb,
        )


def serve(port: int = 50051):
    """Start the gRPC server process."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    order_service_pb2_grpc.add_OrderServiceServicer_to_server(
        OrderServiceServicer(), server
    )
    bind_address = f"0.0.0.0:{port}"
    server.add_insecure_port(bind_address)
    server.start()
    print(f"[{SERVICE_NAME}] Listening on {bind_address}")
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print(f"[{SERVICE_NAME}] Shutting down gracefully...")
        server.stop(0)


if __name__ == "__main__":
    serve(50051)
