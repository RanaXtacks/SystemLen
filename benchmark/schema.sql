-- SystemLens Benchmark: Enterprise SaaS / E-Commerce Schema
-- Realistic PostgreSQL schema with declared FKs, undeclared convention keys, and partitioned tables.

CREATE SCHEMA IF NOT EXISTS public;

-- 1. Authentication & Organization Domain
CREATE TABLE IF NOT EXISTS public.organizations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.accounts (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    balance NUMERIC(12, 2) DEFAULT 0.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.users (
    id SERIAL PRIMARY KEY,
    organization_id INT REFERENCES public.organizations(id),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.user_roles (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    role_name VARCHAR(50) NOT NULL,
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Undeclared FK: org_id -> organizations (abbreviation match)
CREATE TABLE IF NOT EXISTS public.api_tokens (
    id SERIAL PRIMARY KEY,
    token_hash VARCHAR(64) UNIQUE NOT NULL,
    org_id INT NOT NULL,  -- Undeclared reference to organizations(id)
    user_id INT REFERENCES public.users(id),
    expires_at TIMESTAMP
);

-- 2. Billing & Subscription Domain
CREATE TABLE IF NOT EXISTS public.plans (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    price_cents INT NOT NULL,
    billing_interval VARCHAR(20) DEFAULT 'monthly',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES public.users(id),
    plan_id INT NOT NULL REFERENCES public.plans(id),
    status VARCHAR(50) DEFAULT 'active',
    current_period_end TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.payment_methods (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES public.users(id),
    provider VARCHAR(50) NOT NULL,
    last_four VARCHAR(4) NOT NULL,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Undeclared FK: acct_id -> accounts (abbreviation match)
CREATE TABLE IF NOT EXISTS public.invoices (
    id SERIAL PRIMARY KEY,
    acct_id INT NOT NULL,  -- Undeclared reference to accounts(id)
    subscription_id INT REFERENCES public.subscriptions(id),
    total_amount NUMERIC(10, 2) NOT NULL,
    status VARCHAR(50) DEFAULT 'draft',
    due_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.invoice_items (
    id SERIAL PRIMARY KEY,
    invoice_id INT NOT NULL REFERENCES public.invoices(id) ON DELETE CASCADE,
    description VARCHAR(255) NOT NULL,
    amount NUMERIC(10, 2) NOT NULL,
    quantity INT DEFAULT 1
);

-- Undeclared FKs: payment_method_id -> payment_methods, invoice_id -> invoices
CREATE TABLE IF NOT EXISTS public.transactions (
    id SERIAL PRIMARY KEY,
    payment_method_id INT NOT NULL,  -- Undeclared reference to payment_methods(id)
    invoice_id INT,                  -- Undeclared reference to invoices(id)
    amount NUMERIC(10, 2) NOT NULL,
    status VARCHAR(50) NOT NULL,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Catalog & Inventory Domain
CREATE TABLE IF NOT EXISTS public.categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    parent_category_id INT REFERENCES public.categories(id)
);

CREATE TABLE IF NOT EXISTS public.products (
    id SERIAL PRIMARY KEY,
    category_id INT NOT NULL REFERENCES public.categories(id),
    sku VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    is_published BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.inventory_items (
    id SERIAL PRIMARY KEY,
    product_id INT NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
    quantity_on_hand INT DEFAULT 0,
    warehouse_code VARCHAR(50) DEFAULT 'MAIN',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Orders & Fulfillment Domain
CREATE TABLE IF NOT EXISTS public.shipping_addresses (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES public.users(id),
    street_line1 VARCHAR(255) NOT NULL,
    city VARCHAR(100) NOT NULL,
    postal_code VARCHAR(20) NOT NULL,
    country_code VARCHAR(2) DEFAULT 'US'
);

-- Undeclared FK: shipping_address_id -> shipping_addresses (compound role match)
CREATE TABLE IF NOT EXISTS public.orders (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES public.users(id),
    shipping_address_id INT,  -- Undeclared reference to shipping_addresses(id)
    total_amount NUMERIC(10, 2) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    placed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.order_items (
    id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES public.products(id),
    quantity INT NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL
);

-- Undeclared FK: shipping_address_id -> shipping_addresses
CREATE TABLE IF NOT EXISTS public.shipments (
    id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES public.orders(id),
    shipping_address_id INT NOT NULL,  -- Undeclared reference to shipping_addresses(id)
    tracking_number VARCHAR(100),
    carrier VARCHAR(50),
    shipped_at TIMESTAMP
);

-- 5. Audit Logging Domain (Partitioned table)
-- Undeclared FK: usr_id -> users (abbreviation match)
CREATE TABLE IF NOT EXISTS public.audit_logs (
    id BIGSERIAL NOT NULL,
    usr_id INT,  -- Undeclared reference to users(id)
    action VARCHAR(100) NOT NULL,
    entity_name VARCHAR(100) NOT NULL,
    entity_id VARCHAR(64),
    payload JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE IF NOT EXISTS public.audit_logs_2026_q1 PARTITION OF public.audit_logs
    FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');

CREATE TABLE IF NOT EXISTS public.audit_logs_2026_q2 PARTITION OF public.audit_logs
    FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');

-- View
CREATE OR REPLACE VIEW public.v_active_subscriptions AS
    SELECT s.id, s.user_id, p.name AS plan_name, s.current_period_end
    FROM public.subscriptions s
    JOIN public.plans p ON s.plan_id = p.id
    WHERE s.status = 'active';
