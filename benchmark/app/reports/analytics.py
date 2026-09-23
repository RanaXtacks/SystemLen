"""Cross-table reporting and analytics service."""

from typing import Any


def get_monthly_revenue_report(db_cursor: Any) -> list[dict[str, Any]]:
    """Compute monthly revenue by joining transactions and invoices."""
    query = """
        SELECT
            DATE_TRUNC('month', t.processed_at) AS report_month,
            COUNT(t.id) AS transaction_count,
            SUM(t.amount) AS total_revenue
        FROM transactions t
        JOIN invoices i ON t.invoice_id = i.id
        WHERE t.status = 'settled'
        GROUP BY 1
        ORDER BY 1 DESC
    """
    db_cursor.execute(query)
    return db_cursor.fetchall()


def get_top_spending_users(db_cursor: Any, limit: int = 10) -> list[dict[str, Any]]:
    """Find top customers by total order spend."""
    query = """
        SELECT
            u.id,
            u.email,
            u.full_name,
            COUNT(o.id) AS total_orders,
            SUM(o.total_amount) AS total_spend
        FROM users u
        JOIN orders o ON u.id = o.user_id
        WHERE o.status != 'cancelled'
        GROUP BY u.id, u.email, u.full_name
        ORDER BY total_spend DESC
        LIMIT %s
    """
    db_cursor.execute(query, (limit,))
    return db_cursor.fetchall()


def get_low_inventory_alerts(db_cursor: Any, threshold: int = 5) -> list[dict[str, Any]]:
    """Identify products with inventory below threshold."""
    query = """
        SELECT
            p.id,
            p.sku,
            p.name,
            c.name AS category_name,
            i.quantity_on_hand
        FROM products p
        JOIN categories c ON p.category_id = c.id
        JOIN inventory_items i ON p.id = i.product_id
        WHERE i.quantity_on_hand <= %s
        ORDER BY i.quantity_on_hand ASC
    """
    db_cursor.execute(query, (threshold,))
    return db_cursor.fetchall()
