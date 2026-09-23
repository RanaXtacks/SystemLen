"""Authentication and organization service."""

from typing import Any, Optional
from benchmark.app.models import User, Organization


def authenticate_user(session: Any, email: str) -> Optional[User]:
    """Authenticate a user using SQLAlchemy ORM query."""
    return session.query(User).filter_by(email=email).first()


def get_user_organizations(db_cursor: Any, user_id: int) -> list[dict[str, Any]]:
    """Retrieve organization records for a user via joined raw SQL."""
    query = """
        SELECT o.id, o.name, o.slug
        FROM organizations o
        JOIN users u ON u.organization_id = o.id
        WHERE u.id = %s
    """
    db_cursor.execute(query, (user_id,))
    return db_cursor.fetchall()


def create_api_token(db_cursor: Any, token_hash: str, org_id: int, user_id: int) -> None:
    """Insert a new API token linked to an organization and user."""
    query = """
        INSERT INTO api_tokens (token_hash, org_id, user_id)
        VALUES (%s, %s, %s)
    """
    db_cursor.execute(query, (token_hash, org_id, user_id))


def verify_token(db_cursor: Any, token_hash: str) -> Optional[dict[str, Any]]:
    """Check validity of an API token."""
    query = "SELECT * FROM api_tokens WHERE token_hash = %s"
    db_cursor.execute(query, (token_hash,))
    return db_cursor.fetchone()


def assign_user_role(db_cursor: Any, user_id: int, role_name: str) -> None:
    """Assign a role to a user."""
    query = "INSERT INTO user_roles (user_id, role_name) VALUES (%s, %s)"
    db_cursor.execute(query, (user_id, role_name))
