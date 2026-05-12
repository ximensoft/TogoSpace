from unittest.mock import AsyncMock, MagicMock
import pytest
from constants import ToolCategory
from service.agentService.toolRegistry import (
    AgentToolRegistry, 
    validate_tool_allow_specs, 
    build_runtime_allow_specs
)
from service.roomService import ToolCallContext
from util import llmApiUtil

def _register_tools(registry: AgentToolRegistry, *names: str) -> AsyncMock:
    handler = AsyncMock(return_value={"success": True})
    for name in names:
        # 直接构造 OpenAITool
        tool = llmApiUtil.OpenAITool(
            function=llmApiUtil.OpenAIFunction(
                name=name,
                description="",
                parameters=llmApiUtil.OpenAIFunctionParameter(type="object", properties={}, required=[])
            )
        )
        registry.register(tool, handler, marks_turn_finish=name == "finish_chat_turn")
    return handler

def test_validate_tool_allow_specs() -> None:
    # 正常情况 (list_dir 是 READ)
    assert validate_tool_allow_specs(["Category:Read", "list_dir"]) is None
    # 包含 ADMIN 类别
    assert "不允许分配管理员类别权限" in validate_tool_allow_specs(["Category:Admin"])
    # 包含 ADMIN 工具
    assert "不允许分配管理员工具权限" in validate_tool_allow_specs(["save_role_template"])

def test_build_runtime_allow_specs() -> None:
    # 默认权限
    specs = build_runtime_allow_specs(None, is_root_leader=False)
    assert set(specs) == {"Category:Basic", "Category:Read", "Category:Write", "Category:Execute"}
    
    # 指定权限，应自动补齐 Basic
    # list_dir 是 READ
    specs = build_runtime_allow_specs(["list_dir"], is_root_leader=False)
    assert set(specs) == {"list_dir", "Category:Basic"}
    
    # Root Leader 自动补齐 Admin 和 Basic
    specs = build_runtime_allow_specs(None, is_root_leader=True)
    assert "Category:Admin" in specs
    assert "Category:Basic" in specs

def test_registry_register_and_list() -> None:
    registry = AgentToolRegistry()
    # list_dir 是 READ, send_chat_msg 是 BASIC
    _register_tools(registry, "list_dir", "send_chat_msg")
    
    assert set(registry.list_registered_tool_names()) == {"list_dir", "send_chat_msg"}
    assert set(registry.list_enabled_tool_names()) == {"list_dir", "send_chat_msg"}
    
    tool = registry.get_registered_tool("list_dir")
    assert tool.category == ToolCategory.READ
    assert tool.marks_turn_finish is False

def test_registry_clear() -> None:
    registry = AgentToolRegistry()
    _register_tools(registry, "list_dir")
    registry.clear()
    assert registry.list_registered_tool_names() == []

def test_apply_tool_allow_specs() -> None:
    registry = AgentToolRegistry()
    _register_tools(registry, "list_dir", "send_chat_msg", "save_role_template")
    
    # 仅开启 Basic
    registry.apply_tool_allow_specs(["Category:Basic"])
    # send_chat_msg 是 BASIC, list_dir 是 READ
    assert registry.list_enabled_tool_names() == ["send_chat_msg"]
    
    # 仅开启指定工具
    registry.apply_tool_allow_specs(["list_dir"])
    assert registry.list_enabled_tool_names() == ["list_dir"]
    
    # 开启 Read 和具体工具
    registry.apply_tool_allow_specs(["Category:Read", "save_role_template"])
    assert set(registry.list_enabled_tool_names()) == {"list_dir", "save_role_template"}

@pytest.mark.asyncio
async def test_execute_tool_call_success() -> None:
    registry = AgentToolRegistry()
    
    # 显式定义的 handler，方便断言参数
    async def mock_handler(args_str: str, context: ToolCallContext) -> dict:
        return {"success": True, "files": ["a.txt"], "passed_context": context}
        
    tool = llmApiUtil.OpenAITool(
        function=llmApiUtil.OpenAIFunction(
            name="list_dir",
            description="",
            parameters=llmApiUtil.OpenAIFunctionParameter(type="object", properties={}, required=[])
        )
    )
    registry.register(tool, mock_handler)
    
    mock_room = MagicMock()
    ctx = ToolCallContext(agent_id=1, team_id=1, chat_room=mock_room)
    
    result = await registry.execute_tool_call(
        llmApiUtil.OpenAIToolCall(id="tc_1", function={"name": "list_dir", "arguments": "{}"}),
        context=ctx
    )
    
    assert result.success is True
    assert result.result["files"] == ["a.txt"]
    
    called_ctx = result.result["passed_context"]
    assert isinstance(called_ctx, ToolCallContext)
    assert called_ctx.tool_name == "list_dir"
    assert called_ctx.chat_room == mock_room

@pytest.mark.asyncio
async def test_execute_tool_call_unknown_tool() -> None:
    registry = AgentToolRegistry()
    ctx = ToolCallContext(agent_id=1, team_id=1, chat_room=MagicMock())
    result = await registry.execute_tool_call(
        llmApiUtil.OpenAIToolCall(id="tc_1", function={"name": "unknown", "arguments": "{}"}),
        context=ctx
    )
    assert result.success is False
    assert "未知工具" in result.error_message

@pytest.mark.asyncio
async def test_execute_tool_call_disabled_tool() -> None:
    registry = AgentToolRegistry()
    _register_tools(registry, "list_dir")
    registry.apply_tool_allow_specs([]) # 全部禁用
    
    ctx = ToolCallContext(agent_id=1, team_id=1, chat_room=MagicMock())
    result = await registry.execute_tool_call(
        llmApiUtil.OpenAIToolCall(id="tc_1", function={"name": "list_dir", "arguments": "{}"}),
        context=ctx
    )
    assert result.success is False
    assert "工具无权限使用" in result.error_message

@pytest.mark.asyncio
async def test_execute_tool_call_exception() -> None:
    registry = AgentToolRegistry()
    handler = _register_tools(registry, "list_dir")
    handler.side_effect = Exception("boom")
    
    ctx = ToolCallContext(agent_id=1, team_id=1, chat_room=MagicMock())
    result = await registry.execute_tool_call(
        llmApiUtil.OpenAIToolCall(id="tc_1", function={"name": "list_dir", "arguments": "{}"}),
        context=ctx
    )
    assert result.success is False
    assert "工具调用失败" in result.result["message"]
