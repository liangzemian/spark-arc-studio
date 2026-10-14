import queue
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage

from agents.communication import SparkBaseAgent, set_tool_event_sink
from agents.tools import registry
from agents.tools.stream_events import is_tool_result_failure
from core.request_context import current_agent_id
from llm.agen_matchbox.tool_protocol import validate_tool_message_history


class RecordingTool:
    def __init__(self, name):
        self.name = name
        self.args_schema = None
        self.calls = []

    def invoke(self, args):
        self.calls.append((args, current_agent_id.get()))
        return "操作完成"


@pytest.fixture
def execution(monkeypatch):
    agent = SparkBaseAgent("agent_critic", user_id="security-test")
    read = RecordingTool("read_worldview")
    write = RecordingTool("rewrite_worldview")
    monkeypatch.setattr(registry, "TOOLS_BY_NAME", {read.name: read, write.name: write})
    monkeypatch.setattr(registry, "get_tools_for_agent", lambda *_args, **_kwargs: [read])
    sink = queue.Queue()
    token = set_tool_event_sink(sink)
    try:
        yield agent, read, write, sink
    finally:
        set_tool_event_sink(token)


def _call(name):
    return {"name": name, "args": {"content": "正文"}, "id": "call-security"}


def test_agent_cannot_execute_another_agents_tool(execution):
    agent, _, write, sink = execution
    result = agent._execute_tool_calls([_call(write.name)])
    assert write.calls == []
    assert "未授权" in result
    assert is_tool_result_failure(write.name, result)
    events = list(sink.queue)
    assert [event["event"] for event in events] == ["tool_exec_started", "tool_exec_failed"]
    assert events[0]["tool_call_key"] == events[1]["tool_call_key"] == "call-security"
    assert events[1]["tool_error"] == result


def test_authorized_tool_executes_and_restores_agent_context(execution):
    agent, read, _, sink = execution
    before = current_agent_id.get()
    assert agent._execute_tool_calls([_call(read.name)]) == "操作完成"
    assert read.calls == [({"content": "正文"}, "agent_critic")]
    assert current_agent_id.get() == before
    assert list(sink.queue)[-1]["event"] == "tool_exec_finished"


def test_empty_advertised_tool_set_cannot_fall_back_to_global_registry(execution):
    agent, read, _, _ = execution
    result = agent._execute_tool_calls([_call(read.name)], tools_override=[])
    assert read.calls == []
    assert is_tool_result_failure(read.name, result)


def test_override_cannot_grant_another_agents_tool(execution):
    agent, _, write, _ = execution
    result = agent._execute_tool_calls([_call(write.name)], tools_override=[write])
    assert write.calls == []
    assert "未授权" in result


def test_pipeline_uses_its_explicit_advertised_tool_set(execution, monkeypatch):
    agent, read, write, _ = execution
    agent.agent_id = "agent_scriptwriter"
    monkeypatch.setattr(registry, "get_tools_for_agent", lambda *_args, pipeline_mode=False, **_kwargs: [read, write] if pipeline_mode else [read])
    result = agent._execute_tool_calls([_call(write.name)], tools_override=[write], pipeline_mode=True)
    assert result == "操作完成"
    assert len(write.calls) == 1


def test_chat_mode_cannot_execute_pipeline_only_tool(execution, monkeypatch):
    agent, read, write, _ = execution
    monkeypatch.setattr(registry, "get_tools_for_agent", lambda *_args, pipeline_mode=False, **_kwargs: [read, write] if pipeline_mode else [read])
    result = agent._execute_tool_calls([_call(write.name)], tools_override=[write])
    assert write.calls == []
    assert "未授权" in result


def test_unknown_tool_is_a_visible_failure(execution):
    agent, _, _, sink = execution
    result = agent._execute_tool_calls([_call("does_not_exist")])
    assert is_tool_result_failure("does_not_exist", result)
    assert list(sink.queue)[-1]["event"] == "tool_exec_failed"


@pytest.mark.parametrize("streaming", [False, True])
def test_chat_rejects_unadvertised_tool_and_keeps_history_closed(execution, monkeypatch, tmp_path, streaming):
    agent, read, write, _ = execution
    monkeypatch.setattr("core.utils.USERDATA_ROOT", str(tmp_path))
    requests = []
    bound = []
    responses = [AIMessage(content="", tool_calls=[{"name": write.name, "args": {}, "id": "call-denied", "type": "tool_call"}]), AIMessage(content="越权操作已拒绝")]

    class FakeLlm:
        def bind_tools(self, tools):
            bound.append([tool.name for tool in tools])
            return self

        def invoke(self, messages):
            requests.append(list(messages))
            return responses.pop(0)

    client = FakeLlm()
    monkeypatch.setattr("llm.agen_matchbox.matchbox", lambda: SimpleNamespace(get_user_llm=lambda *_args, **_kwargs: client))
    monkeypatch.setattr(agent, "_build_tool_system_prompt", lambda *_args, **_kwargs: "稳定系统协议")
    monkeypatch.setattr(agent, "_build_runtime_tail", lambda **_kwargs: "")

    def budget(**_kwargs):
        return SimpleNamespace(messages=[SystemMessage(content="稳定系统协议"), HumanMessage(content="本轮任务")], checkpoint=None)

    def budget_stream(_func, **kwargs):
        if False:
            yield None
        kwargs.pop("stop_event", None)
        return _func(**kwargs)

    def model_stream(llm, messages, **_kwargs):
        response = llm.invoke(messages)
        yield AIMessageChunk(content=response.content, tool_calls=response.tool_calls)

    monkeypatch.setattr("agents.context_budget.prepare_chat_messages_with_budget", budget)
    monkeypatch.setattr("agents.context_budget.stream_context_budget_events", budget_stream)
    monkeypatch.setattr("agents.context_budget.rebudget_existing_messages", lambda **kwargs: SimpleNamespace(messages=kwargs["messages"]))
    monkeypatch.setattr("agents.communication.stream_model_turn_with_retry", model_stream)
    if streaming:
        events = list(agent.chat_stream("本轮任务", active_context="现场"))
        assert any(isinstance(event, dict) and event.get("event") == "tool_exec_failed" for event in events)
        assert not any(isinstance(event, dict) and event.get("event") == "tool_exec_finished" for event in events)
    else:
        assert agent.chat("本轮任务", active_context="现场") == "越权操作已拒绝"
    assert write.calls == []
    assert bound == [[read.name]]
    assert len(requests) == 2
    assert requests[0][0].content == requests[1][0].content == "稳定系统协议"
    validate_tool_message_history(requests[1])
    result = next(message for message in requests[1] if isinstance(message, ToolMessage))
    assert result.tool_call_id == "call-denied"
    assert "未授权" in result.content
