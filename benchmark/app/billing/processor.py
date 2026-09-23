"""Billing and subscription processing service."""

from typing import Any, Optional
from benchmark.app.models import Subscription, PaymentMethod


def process_subscription_renewals(session: Any) -> list[Subscription]:
    """Find active subscriptions up for renewal using ORM."""
    return session.query(Subscription).filter(Subscription.status == "active").all()


def generate_invoice(db_cursor: Any, acct_id: int, subscription_id: int, total_amount: float, due_date: str) -> int:
    """Create a new invoice for an account."""
    query = """
        INSERT INTO invoices (acct_id, subscription_id, total_amount, due_date)
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """
    db_cursor.execute(query, (acct_id, subscription_id, total_amount, due_date))
    row = db_cursor.fetchone()
    return row[0] if row else 0


def add_invoice_items(db_cursor: Any, invoice_id: int, description: str, amount: float, quantity: int = 1) -> None:
    """Add a line item to an existing invoice."""
    query = """
        INSERT INTO invoice_items (invoice_id, description, amount, quantity)
        VALUES (%s, %s, %s, %s)
    """
    db_cursor.execute(query, (invoice_id, description, amount, quantity))


def charge_payment_method(session: Any, db_cursor: Any, payment_method_id: int, invoice_id: int, amount: float) -> None:
    """Fetch payment method via ORM and record a transaction via raw SQL."""
    pm = session.query(PaymentMethod).get(payment_method_id)
    if pm:
        tx_query = """
            INSERT INTO transactions (payment_method_id, invoice_id, amount, status)
            VALUES (%s, %s, %s, 'settled')
        """
        db_cursor.execute(tx_query, (payment_method_id, invoice_id, amount))


def get_active_subscriptions_view(db_cursor: Any) -> list[dict[str, Any]]:
    """Query the pre-defined view for active subscriptions."""
    query = "SELECT * FROM v_active_subscriptions"
    db_cursor.execute(query)
    return db_cursor.fetchall()
