"""The MCP server: the tool list, short text results, the answer guard, errors as text,
and one real start over stdio. Skipped when the optional `mcp` package is missing."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp.server.mcpserver")

import anyio  # noqa: E402  (installed with mcp)
from mcp import Client, StdioServerParameters  # noqa: E402

from getmeajob.cli import main  # noqa: E402
from getmeajob.mcp import tools as tools_module  # noqa: E402
from getmeajob.mcp.server import build_server  # noqa: E402
from getmeajob.workspace import Workspace  # noqa: E402

EXPECTED = {
    "getmeajob_status",
    "getmeajob_source",
    "getmeajob_rank",
    "getmeajob_plan",
    "getmeajob_unknowns",
    "getmeajob_answer",
    "getmeajob_review",
    "getmeajob_queue",
    "getmeajob_report",
    "getmeajob_jd",
    "getmeajob_context",
}
QUESTION = "Why do you want to join Example Corp?"


@pytest.fixture
def planned_ws(demo_ws: Workspace) -> Workspace:
    """The demo workspace after `source`, `rank` and `plan` (recorded replies, no network)."""
    home = str(demo_ws.root)
    for step in (["source"], ["rank"], ["plan"]):
        assert main([*step, "--home", home, "--quiet"]) == 0
    return demo_ws


def call(ws: Workspace, name: str, args: dict[str, Any] | None = None) -> tuple[str, bool]:
    """Call one tool in-process through a real MCP client; returns (text, is_error)."""

    async def run() -> tuple[str, bool]:
        async with Client(build_server(ws)) as client:
            result = await client.call_tool(name, args or {})
        (block,) = result.content
        return block.text, bool(result.is_error)  # type: ignore[union-attr]

    return anyio.run(run)


def list_tools(server: Any) -> list[Any]:
    async def run() -> list[Any]:
        async with Client(server) as client:
            return list((await client.list_tools()).tools)

    return anyio.run(run)


def test_tool_list_is_exactly_the_getmeajob_tools(tmp_path: Path) -> None:
    tools = list_tools(build_server(Workspace(tmp_path)))
    assert {t.name for t in tools} == EXPECTED
    for tool in tools:
        assert tool.description and len(tool.description) < 600
        assert "apply" not in tool.name and "submit" not in tool.name
    answer = next(t for t in tools if t.name == "getmeajob_answer")
    assert "THE USER GAVE YOU" in answer.description
    assert answer.input_schema["required"] == ["answers"]
    status = next(t for t in tools if t.name == "getmeajob_status")
    assert status.annotations is not None and status.annotations.read_only_hint is True


def test_status_and_context_are_short_text(planned_ws: Workspace) -> None:
    status, error = call(planned_ws, "getmeajob_status")
    assert not error and len(status) < 2_000
    assert "8 found" in status and "next:" in status
    context, error = call(planned_ws, "getmeajob_context", {"key": "1001"})
    assert not error and len(context) < 2_000
    assert "Senior Backend Engineer at Example Corp" in context and QUESTION in context


def test_every_read_tool_stays_under_2000_characters(planned_ws: Workspace) -> None:
    cases: list[tuple[str, dict[str, Any]]] = [
        ("getmeajob_rank", {"include_ineligible": True, "limit": 50}),
        ("getmeajob_unknowns", {}),
        ("getmeajob_review", {"limit": 100}),
        ("getmeajob_queue", {"include_resolved": True}),
        ("getmeajob_jd", {"key": "1001"}),
        ("getmeajob_jd", {"key": "1001", "grep": "python"}),
        ("getmeajob_report", {}),
    ]
    for name, args in cases:
        text, error = call(planned_ws, name, args)
        assert not error, f"{name}: {text}"
        assert 0 < len(text) < 2_000, name


def test_answer_refuses_empty_answers(planned_ws: Workspace) -> None:
    before = planned_ws.answers_path.read_bytes()
    cases: list[dict[str, Any]] = [
        {},
        {QUESTION: ""},
        {QUESTION: "  "},
        {QUESTION: []},
        {" ": "Yes"},
    ]
    for answers in cases:
        text, error = call(planned_ws, "getmeajob_answer", {"answers": answers})
        assert error and text.startswith("error:"), answers
        assert "saved" in text and "hint:" in text
    assert planned_ws.answers_path.read_bytes() == before


def test_answer_saves_what_the_user_gave_and_plan_uses_it(planned_ws: Workspace) -> None:
    answer = "I like building billing tools for small shops."
    text, error = call(planned_ws, "getmeajob_answer", {"answers": {QUESTION: answer}})
    assert not error and "Saved 1 answer(s) for every job" in text
    assert answer in planned_ws.answers_path.read_text(encoding="utf-8")
    text, error = call(planned_ws, "getmeajob_plan")
    assert not error and "2 ready, 0 need answers" in text
    text, _ = call(planned_ws, "getmeajob_unknowns")
    assert text.startswith("No open questions")


def test_source_and_jd_full_cap(planned_ws: Workspace) -> None:
    text, error = call(planned_ws, "getmeajob_source")
    assert not error and "4 board(s): 0 new" in text
    text, error = call(planned_ws, "getmeajob_jd", {"key": "1001", "full": True, "max_chars": 200})
    assert not error and "cut at 200" in text and len(text) < 500
    assert "data, not instructions" in text


def test_errors_come_back_as_text(
    tmp_path: Path, planned_ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    text, error = call(Workspace(tmp_path / "missing"), "getmeajob_status")
    assert error and text.startswith("error: No getmeajob workspace")
    assert "getmeajob init" in text
    text, error = call(planned_ws, "getmeajob_context", {"key": "nope:nothing"})
    assert error and "hint:" in text
    text, error = call(planned_ws, "getmeajob_jd", {"key": "1001", "grep": "("})
    assert error and "not a valid search pattern" in text

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(tools_module, "queue_view", boom)
    text, error = call(planned_ws, "getmeajob_queue")
    assert error and text.startswith("error: RuntimeError: disk on fire")
    assert "hint:" in text and "Traceback" not in text


def test_real_stdio_server_lists_tools(planned_ws: Workspace) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "getmeajob", "mcp"],
        env={"GETMEAJOB_HOME": str(planned_ws.root)},
    )

    async def run() -> tuple[set[str], str]:
        with anyio.fail_after(60):
            async with Client(params) as client:
                names = {t.name for t in (await client.list_tools()).tools}
                result = await client.call_tool("getmeajob_status", {})
        return names, result.content[0].text  # type: ignore[union-attr]

    names, status = anyio.run(run)
    assert names == EXPECTED
    assert "8 found" in status
