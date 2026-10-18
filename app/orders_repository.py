"""
Shared Orders Repository & Persistence Layer.

Provides a unified source of truth and enforces consistent business rules
across both the FastAPI REST interface and the standalone gRPC service.
Backed by SQLite in WAL (Write-Ahead Logging) mode for safe multi-process concurrency.
"""

import json
import os
import sqlite3
import time
from typing import Dict, List, Optional, Tuple, Any

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "cristaux_orders.db")


def get_db_connection() -> sqlite3.Connection:
    """Create a SQLite connection configured for concurrent multi-process access."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def init_db():
    """Initialize database tables and indexes."""
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                customer_email TEXT NOT NULL,
                items_json TEXT NOT NULL,
                total_amount REAL NOT NULL,
                status TEXT NOT NULL,
                cancellation_reason TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """
        )
        conn.commit()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "order_id": row["order_id"],
        "customer_email": row["customer_email"],
        "items": json.loads(row["items_json"]),
        "total_amount": float(row["total_amount"]),
        "status": row["status"],
        "cancellation_reason": row["cancellation_reason"],
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def create_order(
    order_id: str,
    customer_email: str,
    items: List[Dict[str, Any]],
    total_amount: float,
    status: str = "pending",
) -> Dict[str, Any]:
    """Store a newly created order."""
    now = time.time()
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO orders (order_id, customer_email, items_json, total_amount, status, cancellation_reason, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?);
            """,
            (order_id, customer_email, json.dumps(items), total_amount, status, now, now),
        )
        conn.commit()

    return {
        "order_id": order_id,
        "customer_email": customer_email,
        "items": items,
        "total_amount": total_amount,
        "status": status,
        "cancellation_reason": None,
        "created_at": now,
        "updated_at": now,
    }


def get_order(order_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve an order by ID."""
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM orders WHERE order_id = ?;", (order_id,))
        row = cursor.fetchone()
        if row:
            return _row_to_dict(row)
    return None


def list_orders() -> List[Dict[str, Any]]:
    """Retrieve all placed orders ordered by creation timestamp."""
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM orders ORDER BY created_at DESC;")
        return [_row_to_dict(r) for r in cursor.fetchall()]


def cancel_order(
    order_id: str,
    reason: str = "customer_request",
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Enforces shared domain business rules for order cancellation:
    1. Returns (False, "NOT_FOUND", None) if order does not exist.
    2. Returns (False, "ALREADY_CANCELLED", order) if already cancelled.
    3. Returns (False, "ALREADY_FULFILLED", order) if fulfilled.
    4. Returns (True, "SUCCESS", updated_order) if successfully cancelled.
    """
    now = time.time()
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM orders WHERE order_id = ?;", (order_id,))
        row = cursor.fetchone()
        if not row:
            return False, "NOT_FOUND", None

        order = _row_to_dict(row)
        if order["status"] == "cancelled":
            return False, "ALREADY_CANCELLED", order

        if order["status"] == "fulfilled":
            return False, "ALREADY_FULFILLED", order

        conn.execute(
            """
            UPDATE orders
            SET status = 'cancelled', cancellation_reason = ?, updated_at = ?
            WHERE order_id = ?;
            """,
            (reason, now, order_id),
        )
        conn.commit()

        order["status"] = "cancelled"
        order["cancellation_reason"] = reason
        order["updated_at"] = now
        return True, "SUCCESS", order


def fulfill_order(order_id: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Enforces shared domain business rules for order fulfillment.
    """
    now = time.time()
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM orders WHERE order_id = ?;", (order_id,))
        row = cursor.fetchone()
        if not row:
            return False, "NOT_FOUND", None

        order = _row_to_dict(row)
        if order["status"] == "fulfilled":
            return False, "ALREADY_FULFILLED", order

        if order["status"] == "cancelled":
            return False, "ALREADY_CANCELLED", order

        conn.execute(
            """
            UPDATE orders
            SET status = 'fulfilled', updated_at = ?
            WHERE order_id = ?;
            """,
            (now, order_id),
        )
        conn.commit()

        order["status"] = "fulfilled"
        order["updated_at"] = now
        return True, "SUCCESS", order


# Initialize tables on import
init_db()
