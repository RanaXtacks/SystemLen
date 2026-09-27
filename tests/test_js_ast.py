"""Unit tests for JavaScript/TypeScript AST Adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from systemlens.adapters.js_ast import JavaScriptASTAdapter
from systemlens.models import EdgeType, NodeType


def test_extract_knex_and_prisma(tmp_path):
    js_code = """
    // Service function using Knex and Prisma
    async function getUserOrders(userId) {
        const orders = await knex('orders').where({ user_id: userId });
        const user = await prisma.user.findUnique({ where: { id: userId } });
        return { user, orders };
    }
    """
    file_path = tmp_path / "service.js"
    file_path.write_text(js_code, encoding="utf-8")

    adapter = JavaScriptASTAdapter(src_dir=tmp_path)
    nodes = adapter.extract_nodes()
    edges = adapter.extract_edges()

    # Nodes should contain file and function
    node_ids = {n.id for n in nodes}
    assert "file:service.js" in node_ids
    assert "func:service.js:getUserOrders" in node_ids

    # Edges should contain knex (orders) and prisma (users)
    orm_edges = [e for e in edges if e.type == EdgeType.ORM_CALL]
    assert len(orm_edges) == 2
    targets = {e.target for e in orm_edges}
    assert "table:orders" in targets
    assert "table:users" in targets


def test_extract_sequelize(tmp_path):
    ts_code = """
    export const fetchProducts = async () => {
        const items = await Product.findAll({ limit: 10 });
        return items;
    };
    """
    file_path = tmp_path / "products.ts"
    file_path.write_text(ts_code, encoding="utf-8")

    adapter = JavaScriptASTAdapter(src_dir=tmp_path)
    edges = adapter.extract_edges()

    orm_edges = [e for e in edges if e.type == EdgeType.ORM_CALL]
    assert len(orm_edges) == 1
    assert orm_edges[0].target == "table:products"
    assert orm_edges[0].source == "func:products.ts:fetchProducts"


def test_extract_raw_sql_literal(tmp_path):
    js_code = """
    function getBillingHistory(accountId) {
        const query = `SELECT id, amount FROM invoices WHERE account_id = $1`;
        return client.query(query);
    }
    """
    file_path = tmp_path / "billing.js"
    file_path.write_text(js_code, encoding="utf-8")

    adapter = JavaScriptASTAdapter(src_dir=tmp_path)
    edges = adapter.extract_edges()

    sql_edges = [e for e in edges if e.type == EdgeType.STATIC_SQL_STRING]
    assert len(sql_edges) == 1
    assert sql_edges[0].target == "table:invoices"
    assert sql_edges[0].confidence == 0.85


def test_extract_dynamic_unresolved(tmp_path):
    js_code = """
    function executeCustomReport(sqlStatement) {
        return client.query(sqlStatement);
    }
    """
    file_path = tmp_path / "report.js"
    file_path.write_text(js_code, encoding="utf-8")

    adapter = JavaScriptASTAdapter(src_dir=tmp_path)
    edges = adapter.extract_edges()

    dynamic_edges = [e for e in edges if e.type == EdgeType.DYNAMIC_UNRESOLVED]
    assert len(dynamic_edges) == 1
    assert dynamic_edges[0].target == "table:unresolved"
    assert dynamic_edges[0].confidence == 0.15


def test_structural_belongs_to_edges(tmp_path):
    js_code = """
    function first() {}
    function second() {}
    """
    file_path = tmp_path / "utils.js"
    file_path.write_text(js_code, encoding="utf-8")

    adapter = JavaScriptASTAdapter(src_dir=tmp_path)
    edges = adapter.extract_edges()

    struct_edges = [e for e in edges if e.type == EdgeType.STRUCTURAL_BELONGS_TO]
    assert len(struct_edges) == 2
    assert all(e.target == "file:utils.js" for e in struct_edges)
    assert all(e.confidence == 1.0 for e in struct_edges)


def test_extract_raw_catalog(tmp_path):
    js_code = "function test() {}"
    (tmp_path / "index.js").write_text(js_code, encoding="utf-8")

    adapter = JavaScriptASTAdapter(src_dir=tmp_path)
    catalog = adapter.extract_raw_catalog()
    assert catalog["source_type"] == "javascript"
    assert catalog["files_count"] == 1
    assert catalog["functions_count"] == 1
