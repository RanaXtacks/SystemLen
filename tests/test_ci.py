"""Unit tests for SystemLens CI/PR Integration Module."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from systemlens.ci import (
    CIDiffReport,
    CISummary,
    detect_affected_tables,
    format_json_report,
    format_markdown_report,
    parse_diff_output,
    parse_git_diff,
    run_ci_impact,
)
from systemlens.models import EdgeType, NodeType


@pytest.fixture
def sample_ci_graph() -> dict:
    """Fixture containing a cross-layer graph for CI testing."""
    return {
        "nodes": [
            {"id": "table:public.users", "type": "table", "name": "users", "source_system": "postgres"},
            {"id": "table:public.orders", "type": "table", "name": "orders", "source_system": "postgres"},
            {"id": "table:public.order_items", "type": "table", "name": "order_items", "source_system": "postgres"},
            {"id": "func:app/auth.py:login", "type": "function", "name": "login", "source_system": "python", "metadata": {"file": "app/auth.py", "lineno": 10}},
            {"id": "func:app/billing.py:charge", "type": "function", "name": "charge", "source_system": "python", "metadata": {"file": "app/billing.py", "lineno": 20}},
            {"id": "file:app/auth.py", "type": "file", "name": "app/auth.py", "source_system": "python"},
            {"id": "file:app/billing.py", "type": "file", "name": "app/billing.py", "source_system": "python"},
        ],
        "edges": [
            {"source": "table:public.orders", "target": "table:public.users", "type": "declared_fk", "confidence": 1.0, "evidence": "FK"},
            {"source": "table:public.order_items", "target": "table:public.orders", "type": "declared_fk", "confidence": 1.0, "evidence": "FK"},
            {"source": "func:app/auth.py:login", "target": "table:public.users", "type": "orm_call", "confidence": 0.8, "evidence": "User.objects.get()"},
            {"source": "func:app/billing.py:charge", "target": "table:public.orders", "type": "static_sql_string", "confidence": 0.85, "evidence": "SELECT * FROM orders"},
            {"source": "func:app/auth.py:login", "target": "file:app/auth.py", "type": "structural_belongs_to", "confidence": 1.0, "evidence": "belongs to"},
            {"source": "func:app/billing.py:charge", "target": "file:app/billing.py", "type": "structural_belongs_to", "confidence": 1.0, "evidence": "belongs to"},
        ],
    }


def test_parse_diff_output():
    diff_text = """
    app/auth.py
    migrations\\001_create_users.sql
    ./tests/test_auth.py
    
    """
    files = parse_diff_output(diff_text)
    assert files == [
        "app/auth.py",
        "migrations/001_create_users.sql",
        "tests/test_auth.py",
    ]


def test_parse_git_diff_success(monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value.stdout = "app/auth.py\napp/models.py\n"
    monkeypatch.setattr(subprocess, "run", mock_run)

    result = parse_git_diff(base="main", head="feature")
    assert result == ["app/auth.py", "app/models.py"]
    mock_run.assert_called_once()
    assert "main...feature" in mock_run.call_args[0][0]


def test_parse_git_diff_fallback_to_two_dot(monkeypatch):
    calls = []

    def mock_run(cmd, **kwargs):
        calls.append(cmd)
        if "main...feature" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr="fatal: bad revision 'main...feature'")
        mock_res = MagicMock()
        mock_res.stdout = "services.py\n"
        return mock_res

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = parse_git_diff(base="main", head="feature")
    assert result == ["services.py"]
    assert len(calls) == 2
    assert "main...feature" in calls[0]
    assert "feature" in calls[1]


def test_parse_git_diff_failure(monkeypatch):
    def mock_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(128, cmd, stderr="fatal: Not a git repository")

    monkeypatch.setattr(subprocess, "run", mock_run)

    with pytest.raises(RuntimeError, match="Git diff failed"):
        parse_git_diff(base="main", head="HEAD")


def test_detect_affected_tables_python_file(sample_ci_graph):
    # Changing app/auth.py should affect the 'users' table
    tables = detect_affected_tables(["app/auth.py"], sample_ci_graph)
    assert tables == ["users"]


def test_detect_affected_tables_multiple_files(sample_ci_graph):
    # Changing both auth.py and billing.py should affect 'orders' and 'users'
    tables = detect_affected_tables(["app/auth.py", "app/billing.py"], sample_ci_graph)
    assert sorted(tables) == ["orders", "users"]


def test_detect_affected_tables_sql_filename(sample_ci_graph):
    # Changing migrations/001_create_users.sql matches 'users' table name
    tables = detect_affected_tables(["migrations/001_create_users.sql"], sample_ci_graph)
    assert tables == ["users"]


def test_detect_affected_tables_unrelated_file(sample_ci_graph):
    # Changing README.md or frontend file touches no tables
    tables = detect_affected_tables(["README.md", "static/main.js"], sample_ci_graph)
    assert tables == []


def test_run_ci_impact_full(sample_ci_graph):
    report = run_ci_impact(
        changed_files=["app/auth.py"],
        graph_data=sample_ci_graph,
        max_depth=2,
        high_risk_threshold=2,
    )

    assert isinstance(report, CIDiffReport)
    assert report.changed_files == ["app/auth.py"]
    assert report.affected_tables == ["users"]
    assert len(report.impact_results) == 1

    users_res = report.impact_results[0]
    assert users_res.target_name == "users"
    # Reachable from users: orders (FK), login (function), auth.py (file)
    assert users_res.total_impacted >= 2

    # Check summary
    summary = report.summary
    assert isinstance(summary, CISummary)
    assert summary.total_changed_files == 1
    assert summary.total_affected_tables == 1
    assert summary.total_impacted_entities == users_res.total_impacted
    assert summary.max_blast_radius == users_res.total_impacted
    assert "users" in summary.high_risk_changes


def test_format_markdown_report_with_impact(sample_ci_graph):
    report = run_ci_impact(
        changed_files=["app/auth.py", "app/billing.py"],
        graph_data=sample_ci_graph,
        max_depth=2,
        high_risk_threshold=2,
    )

    md = format_markdown_report(report, high_risk_threshold=2)
    assert "## 🔍 SystemLens Impact Analysis" in md
    assert "Changed Files (2)" in md
    assert "Blast Radius Summary" in md
    assert "Affected Tables (2)" in md
    assert "#### 🗄️ `users`" in md
    assert "#### 🗄️ `orders`" in md
    assert "Blind Spots" in md


def test_format_markdown_report_empty():
    summary = CISummary(0, 0, 0, 0, [])
    report = CIDiffReport([], [], [], summary)
    md = format_markdown_report(report)
    assert "No changed files detected" in md


def test_format_markdown_report_no_affected_tables():
    summary = CISummary(1, 0, 0, 0, [])
    report = CIDiffReport(["docs/readme.md"], [], [], summary)
    md = format_markdown_report(report)
    assert "No database tables or downstream dependencies affected" in md


def test_format_json_report(sample_ci_graph):
    report = run_ci_impact(
        changed_files=["app/auth.py"],
        graph_data=sample_ci_graph,
    )
    json_str = format_json_report(report)
    data = json.loads(json_str)
    assert "changed_files" in data
    assert "affected_tables" in data
    assert "impact_results" in data
    assert "summary" in data
    assert data["summary"]["total_changed_files"] == 1
    assert data["summary"]["total_affected_tables"] == 1
