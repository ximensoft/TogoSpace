"""test_dept_service_sub 单元测试：测试部门下属查询。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from model.dbModel.gtDept import GtDept
from service import deptService


@pytest.fixture
def dept_tree():
    """构造真实部门树对象，验证递归下属查询逻辑。"""
    child = GtDept()
    child.id = 2
    child.manager_id = 20
    child.agent_ids = [20, 21, 22]
    child.children = []

    root = GtDept()
    root.id = 1
    root.manager_id = 10
    root.agent_ids = [10, 11]
    root.children = [child]

    return root


@pytest.mark.asyncio
async def test_get_sub_agent_ids_for_root_manager(dept_tree):
    with patch("service.deptService.get_dept_tree", new=AsyncMock(return_value=dept_tree)):
        result = await deptService.get_sub_agent_ids(team_id=1, agent_id=10)

    assert result == {11, 20, 21, 22}


@pytest.mark.asyncio
async def test_get_sub_agent_ids_for_child_manager(dept_tree):
    with patch("service.deptService.get_dept_tree", new=AsyncMock(return_value=dept_tree)):
        result = await deptService.get_sub_agent_ids(team_id=1, agent_id=20)

    assert result == {21, 22}


@pytest.mark.asyncio
async def test_get_sub_agent_ids_for_non_manager_returns_empty_set(dept_tree):
    with patch("service.deptService.get_dept_tree", new=AsyncMock(return_value=dept_tree)):
        result = await deptService.get_sub_agent_ids(team_id=1, agent_id=11)

    assert result == set()


@pytest.mark.asyncio
async def test_get_sub_agent_ids_for_agent_not_in_tree_returns_empty_set(dept_tree):
    with patch("service.deptService.get_dept_tree", new=AsyncMock(return_value=dept_tree)):
        result = await deptService.get_sub_agent_ids(team_id=1, agent_id=99)

    assert result == set()


@pytest.mark.asyncio
async def test_get_sub_agent_ids_returns_empty_set_when_tree_is_none():
    with patch("service.deptService.get_dept_tree", new=AsyncMock(return_value=None)):
        result = await deptService.get_sub_agent_ids(team_id=1, agent_id=10)

    assert result == set()
