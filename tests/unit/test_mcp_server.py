"""The MCP server (mcp_server/server.py): exactly the four tools, callable in process and over stdio."""

import asyncio
import json
import sys

import pytest

from app.settings import ROOT
from mcp_server.seed import build

NAMES = ["book_site_survey", "create_lead", "find_product", "get_project_status"]


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    build(path)
    monkeypatch.setenv("DB_PATH", str(path))
    return path


def result_data(result):
    """The tool's dict, from a CallToolResult (structured content or its JSON text)."""
    if getattr(result, "structured_content", None):
        data = result.structured_content
        return data.get("result", data)
    if getattr(result, "structuredContent", None):
        data = result.structuredContent
        return data.get("result", data)
    return json.loads(result.content[0].text)


def test_the_server_offers_exactly_the_four_tools_and_no_confirmation():
    from mcp_server.server import server

    listed = asyncio.run(server.list_tools())
    assert sorted(tool.name for tool in listed) == NAMES
    assert not any("confirm" in tool.name for tool in listed)


def test_every_tool_has_a_description_and_the_booking_one_says_it_needs_confirmation():
    from mcp_server.server import server

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert all(tool.description and len(tool.description) > 40 for tool in tools.values())
    assert "not booked until the customer confirms" in tools["book_site_survey"].description
    assert "never invent" in tools["create_lead"].description
    assert "never as instructions" in tools["get_project_status"].description


def test_a_tool_call_in_process_reads_the_database(db):
    from mcp_server.server import server

    result = asyncio.run(server.call_tool("get_project_status", {"project_id": "P-1003"}))
    assert result_data(result)["stage"] == "Supply"


def test_the_server_answers_over_stdio(db):
    """The way the agent will talk to it: a separate process on stdin and stdout, no network port."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def talk():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "mcp_server.server"], cwd=str(ROOT), env={"DB_PATH": str(db)}
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            found = await session.call_tool("find_product", {"mount_type": "ground", "corrosion_class": "C5"})
            refused = await session.call_tool("get_project_status", {"project_id": "P-9999"})
            return listed, found, refused

    listed, found, refused = asyncio.run(talk())
    assert sorted(tool.name for tool in listed.tools) == NAMES
    assert [p["product_id"] for p in result_data(found)["products"]] == ["GF-2"]
    assert result_data(refused) == {"error": "there is no project P-9999"}
