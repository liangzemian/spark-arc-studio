import json
import pickle
from pathlib import Path

import networkx as nx
import pytest

from agents.graphrag.service import GraphRAGService
from agents.graphrag.character_service import CharacterGraphService


@pytest.fixture(params=[GraphRAGService, CharacterGraphService])
def service(request, monkeypatch, tmp_path):
    monkeypatch.setattr("core.utils.USERDATA_ROOT", str(tmp_path))
    instance = request.param("1", "项目")
    Path(instance._artifacts.base_dir).mkdir(parents=True)
    return instance


def _graph():
    graph = nx.Graph(source="世界观")
    graph.add_node("角色甲", aliases="甲", count=2)
    graph.add_edge("角色甲", "角色乙", relation="盟友", evidence_count=3, score=0.75)
    return graph


def test_graph_roundtrip_does_not_write_pickle(service):
    graph = _graph()
    service._persist(graph, {"nodes": 2, "edges": 1})
    loaded = service._load_graph()
    assert nx.utils.graphs_equal(graph, loaded)
    assert not (Path(service._artifacts.base_dir) / "graph.pkl").exists()
    assert service.get_status(check_freshness=False)["graph_ready"] is True


def test_existing_json_is_loaded_without_opening_pickle(service, monkeypatch):
    artifacts = service._artifacts
    Path(artifacts.json_path).write_text(json.dumps(nx.node_link_data(_graph(), edges="edges")), encoding="utf-8")
    (Path(artifacts.base_dir) / "graph.pkl").write_bytes(b"untrusted legacy bytes")
    monkeypatch.setattr(pickle, "load", lambda *_: pytest.fail("不应反序列化旧 pickle"))
    assert nx.utils.graphs_equal(_graph(), service._load_graph())
    assert service.get_build_state()["status"] == "ready"


def test_legacy_graphml_remains_readable(service, monkeypatch):
    nx.write_graphml(_graph(), service._artifacts.graphml_path)
    (Path(service._artifacts.base_dir) / "graph.pkl").write_bytes(b"untrusted legacy bytes")
    monkeypatch.setattr(pickle, "load", lambda *_: pytest.fail("不应反序列化旧 pickle"))
    loaded = service._load_graph()
    assert dict(loaded.nodes(data=True)) == dict(_graph().nodes(data=True))
    assert dict(loaded["角色甲"]["角色乙"]) == dict(_graph()["角色甲"]["角色乙"])
    assert loaded.graph["source"] == "世界观"


def test_pickle_only_is_not_a_ready_index(service, monkeypatch):
    (Path(service._artifacts.base_dir) / "graph.pkl").write_bytes(b"untrusted legacy bytes")
    monkeypatch.setattr(pickle, "load", lambda *_: pytest.fail("不应反序列化旧 pickle"))
    with pytest.raises(FileNotFoundError):
        service._load_graph()
    assert service.get_build_state()["status"] == "not_built"
    assert service.get_status(check_freshness=False)["graph_ready"] is False


def test_invalid_json_cannot_fall_back_to_pickle(service, monkeypatch):
    Path(service._artifacts.json_path).write_text("invalid JSON", encoding="utf-8")
    (Path(service._artifacts.base_dir) / "graph.pkl").write_bytes(b"untrusted legacy bytes")
    monkeypatch.setattr(pickle, "load", lambda *_: pytest.fail("不应反序列化旧 pickle"))
    with pytest.raises(ValueError):
        service._load_graph()
