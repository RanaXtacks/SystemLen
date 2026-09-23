"""Checkout and order processing service."""

from typing import Any
from benchmark.app.models import User, Order, Shipment


def place_order(session: Any, db_cursor: Any, user_id: int, shipping_address_id: int, items: list[dict[str, Any]], total: float) -> int:
    """Create an order with line items."""
    # Verify user exists
    user = session.query(User).get(user_id)
    if not user:
        raise ValueError("User not found")

    order_query = """
        INSERT INTO orders (user_id, shipping_address_id, total_amount, status)
        VALUES (%s, %s, %s, 'pending')
        RETURNING id
    """
    db_cursor.execute(order_query, (user_id, shipping_address_id, total))
    order_id = db_cursor.fetchone()[0]

    for item in items:
        item_query = """
            INSERT INTO order_items (order_id, product_id, quantity, unit_price)
            VALUES (%s, %s, %s, %s)
        """
        db_cursor.execute(item_query, (order_id, item["product_id"], item["quantity"], item["unit_price"]))

    return order_id


def dispatch_shipment(db_cursor: Any, order_id: int, shipping_address_id: int, carrier: str, tracking_number: str) -> None:
    """Create shipment and update order status."""
    ship_query = """
        INSERT INTO shipments (order_id, shipping_address_id, tracking_number, carrier, shipped_at)
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
    """
    db_cursor.execute(ship_query, (order_id, shipping_address_id, tracking_number, carrier))

    update_query = "UPDATE orders SET status = 'shipped' WHERE id = %s"
    db_cursor.execute(update_query, (order_id,))


def get_user_order_history(db_cursor: Any, user_id: int) -> list[dict[str, Any]]:
    """Retrieve full order history for a user."""
    query = """
        SELECT o.id, o.total_amount, o.status, s.tracking_number, s.carrier
        FROM orders o
        LEFT JOIN shipments s ON s.order_id = o.id
        WHERE o.user_id = %s
        ORDER BY o.placed_at DESC
    """
    db_cursor.execute(query, (user_id,))
    return db_cursor.fetchall()
