"""Tests for core Node and Edge models."""

from systemlens.models import BASE_WEIGHTS, Edge, EdgeType, Node, NodeType


def test_node_creation_and_dict():
    node = Node(
        id="table:public.users",
        type=NodeType.TABLE,
        name="users",
        source_system="postgres",
        metadata={"columns": [{"name": "id", "data_type": "integer"}]},
    )

    data = node.to_dict()
    assert data["id"] == "table:public.users"
    assert data["type"] == "table"
    assert data["name"] == "users"
    assert data["source_system"] == "postgres"
    assert len(data["metadata"]["columns"]) == 1

    restored = Node.from_dict(data)
    assert restored.id == node.id
    assert restored.type == NodeType.TABLE
    assert restored.name == node.name


def test_edge_creation_and_confidence_bounds():
    edge = Edge(
        source="table:public.orders",
        target="table:public.users",
        type=EdgeType.DECLARED_FK,
        confidence=1.0,
        evidence="FOREIGN KEY (user_id) REFERENCES users(id)",
    )

    assert edge.confidence == 1.0
    data = edge.to_dict()
    assert data["type"] == "declared_fk"
    assert data["confidence"] == 1.0

    restored = Edge.from_dict(data)
    assert restored.source == edge.source
    assert restored.target == edge.target
    assert restored.type == EdgeType.DECLARED_FK

    # Test confidence clamping
    over_edge = Edge(
        source="a",
        target="b",
        type=EdgeType.DECLARED_FK,
        confidence=1.5,
        evidence="test",
    )
    assert over_edge.confidence == 1.0

    under_edge = Edge(
        source="a",
        target="b",
        type=EdgeType.DYNAMIC_UNRESOLVED,
        confidence=-0.2,
        evidence="test",
    )
    assert under_edge.confidence == 0.0


def test_base_weights_match_tech_spec():
    assert BASE_WEIGHTS[EdgeType.DECLARED_FK] == 1.0
    assert BASE_WEIGHTS[EdgeType.STATIC_SQL_STRING] == 0.85
    assert BASE_WEIGHTS[EdgeType.ORM_CALL] == 0.80
    assert BASE_WEIGHTS[EdgeType.INFERRED_NAMING] == 0.55
    assert BASE_WEIGHTS[EdgeType.DYNAMIC_UNRESOLVED] == 0.15
