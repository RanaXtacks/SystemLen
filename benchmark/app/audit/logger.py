"""Audit trail logging and query service."""

from typing import Any, Optional
import json


def log_audit_event(db_cursor: Any, usr_id: Optional[int], action: str, entity_name: str, entity_id: str, payload: dict[str, Any]) -> None:
    """Log an audit event using static SQL insert."""
    query = """
        INSERT INTO audit_logs (usr_id, action, entity_name, entity_id, payload)
        VALUES (%s, %s, %s, %s, %s)
    """
    db_cursor.execute(query, (usr_id, action, entity_name, entity_id, json.dumps(payload)))


def search_logs_by_user(db_cursor: Any, usr_id: int) -> list[dict[str, Any]]:
    """Query audit logs for a specific user using static SQL."""
    query = "SELECT * FROM audit_logs WHERE usr_id = %s ORDER BY created_at DESC"
    db_cursor.execute(query, (usr_id,))
    return db_cursor.fetchall()


def query_audit_logs_dynamic(db_cursor: Any, target_table: str, filter_expr: str) -> list[dict[str, Any]]:
    """
    Execute a dynamic audit query built via string formatting.
    This intentionally tests the honesty layer (dynamic_unresolved, c=0.15).
    """
    dynamic_sql = f"SELECT * FROM {target_table} WHERE {filter_expr} ORDER BY id DESC LIMIT 100"
    db_cursor.execute(dynamic_sql)
    return db_cursor.fetchall()
