"""SQLAlchemy-style models for benchmark application."""

class User:
    __tablename__ = "users"
    id: int
    organization_id: int
    email: str
    password_hash: str
    full_name: str
    is_active: bool


class Account:
    __tablename__ = "accounts"
    id: int
    name: str
    currency: str
    balance: float


class Organization:
    __tablename__ = "organizations"
    id: int
    name: str
    slug: str


class Plan:
    __tablename__ = "plans"
    id: int
    name: str
    price_cents: int
    billing_interval: str


class Subscription:
    __tablename__ = "subscriptions"
    id: int
    user_id: int
    plan_id: int
    status: str


class PaymentMethod:
    __tablename__ = "payment_methods"
    id: int
    user_id: int
    provider: str
    last_four: str
    is_default: bool


class Invoice:
    __tablename__ = "invoices"
    id: int
    acct_id: int
    subscription_id: int
    total_amount: float
    status: str


class Product:
    __tablename__ = "products"
    id: int
    category_id: int
    sku: str
    name: str
    price: float
    is_published: bool


class Order:
    __tablename__ = "orders"
    id: int
    user_id: int
    shipping_address_id: int
    total_amount: float
    status: str


class Shipment:
    __tablename__ = "shipments"
    id: int
    order_id: int
    shipping_address_id: int
    tracking_number: str
    carrier: str


class AuditLog:
    __tablename__ = "audit_logs"
    id: int
    usr_id: int
    action: str
    entity_name: str
    entity_id: str
