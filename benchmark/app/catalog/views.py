"""Product catalog and inventory inspection service."""

from typing import Any, Optional
from benchmark.app.models import Product


def list_products_by_category(session: Any, category_id: int) -> list[Product]:
    """Retrieve all published products in a category using ORM."""
    return (
        session.query(Product)
        .filter(Product.category_id == category_id, Product.is_published.is_(True))
        .all()
    )


def get_product_detail(db_cursor: Any, product_id: int) -> Optional[dict[str, Any]]:
    """Fetch product details joined with category metadata."""
    query = """
        SELECT p.id, p.sku, p.name, p.price, c.name AS category_name
        FROM products p
        JOIN categories c ON p.category_id = c.id
        WHERE p.id = %s
    """
    db_cursor.execute(query, (product_id,))
    return db_cursor.fetchone()


def check_product_inventory(db_cursor: Any, product_id: int) -> int:
    """Check available warehouse inventory for a product."""
    query = """
        SELECT COALESCE(SUM(quantity_on_hand), 0)
        FROM inventory_items
        WHERE product_id = %s
    """
    db_cursor.execute(query, (product_id,))
    row = db_cursor.fetchone()
    return int(row[0]) if row else 0
