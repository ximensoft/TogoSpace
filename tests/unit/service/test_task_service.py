"""test_task_service 单元测试：测试任务服务。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from constants import TaskPriority, TaskStatus
from model.dbModel.gtAgentTask import GtAgentTask
from service import taskService


@pytest.fixture
def task_manager_mock():
    """统一 mock 任务 DAL，避免访问真实数据库。"""
    with patch("service.taskService.gtAgentTaskManager") as mock_manager:
        yield mock_manager


@pytest.fixture(autouse=True)
def mock_model_to_dict():
    """简化 peewee model_to_dict，便于对 MagicMock 断言。"""

    def _fake_model_to_dict(task, recurse=False):
        status = getattr(task, "status", None)
        priority = getattr(task, "priority", None)
        return {
            "id": getattr(task, "id", None),
            "team_id": getattr(task, "team_id", None),
            "title": getattr(task, "title", None),
            "description": getattr(task, "description", ""),
            "assignee_id": getattr(task, "assignee_id", None),
            "creator_id": getattr(task, "creator_id", None),
            "manager_id": getattr(task, "manager_id", None),
            "status": status.value if isinstance(status, TaskStatus) else status,
            "priority": priority.value if isinstance(priority, TaskPriority) else priority,
            "depends_on": list(getattr(task, "depends_on", []) or []),
            "result": getattr(task, "result", ""),
            "block_reason": getattr(task, "block_reason", ""),
        }

    with patch("playhouse.shortcuts.model_to_dict", side_effect=_fake_model_to_dict):
        yield


@pytest.fixture
def saved_task():
    task = MagicMock(spec=GtAgentTask)
    task.id = 42
    return task


def _build_task(**overrides):
    """构造任务 mock，减少重复样板代码。"""
    task = MagicMock(spec=GtAgentTask)
    task.id = overrides.get("id", 1)
    task.team_id = overrides.get("team_id", 1)
    task.title = overrides.get("title", "test task")
    task.description = overrides.get("description", "")
    task.assignee_id = overrides.get("assignee_id", 11)
    task.creator_id = overrides.get("creator_id", 11)
    task.manager_id = overrides.get("manager_id")
    task.status = overrides.get("status", TaskStatus.TODO)
    task.priority = overrides.get("priority", TaskPriority.NORMAL)
    task.depends_on = overrides.get("depends_on", [])
    task.result = overrides.get("result", "")
    task.block_reason = overrides.get("block_reason", "")
    return task


@pytest.mark.asyncio
async def test_create_task_same_assignee_and_manager_returns_failure(task_manager_mock):
    """assignee 与 manager 相同时，应拒绝创建任务。"""
    result = await taskService.create_task(
        team_id=1,
        creator_id=11,
        title="self review",
        assignee_id=11,
        manager_id=11,
    )

    assert result["success"] is False
    assert result["error_code"] == "invalid_manager"
    assert "manager" in result["message"]
    task_manager_mock.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_create_task_success_self_assign(task_manager_mock, saved_task):
    """创建人给自己派单时应成功创建任务。"""
    task_manager_mock.create_task = AsyncMock(return_value=saved_task)

    result = await taskService.create_task(
        team_id=1,
        creator_id=11,
        title="self task",
        assignee_id=11,
        description="desc",
    )

    assert result == {"success": True, "task_id": 42, "message": "任务已创建，task_id=42，状态=TODO"}
    task_manager_mock.create_task.assert_awaited_once()
    created_task = task_manager_mock.create_task.await_args.args[0]
    assert isinstance(created_task, GtAgentTask)
    assert created_task.team_id == 1
    assert created_task.creator_id == 11
    assert created_task.assignee_id == 11
    assert created_task.title == "self task"
    assert created_task.description == "desc"
    assert created_task.status == TaskStatus.TODO
    assert created_task.priority == TaskPriority.NORMAL


@pytest.mark.asyncio
async def test_create_task_success_manager_assigns_subordinate(task_manager_mock, saved_task):
    """部门主管可以给下属派发任务。"""
    task_manager_mock.create_task = AsyncMock(return_value=saved_task)

    with patch("service.deptService.get_sub_agent_ids", new=AsyncMock(return_value={21, 22})):
        result = await taskService.create_task(
            team_id=1,
            creator_id=20,
            title="assign task",
            assignee_id=21,
            manager_id=20,
        )

    assert result["success"] is True
    assert result["task_id"] == 42
    created_task = task_manager_mock.create_task.await_args.args[0]
    assert created_task.assignee_id == 21
    assert created_task.manager_id == 20


@pytest.mark.asyncio
async def test_create_task_permission_denied_when_assigning_non_subordinate(task_manager_mock):
    """非主管给他人派单时应被拒绝。"""
    with patch("service.deptService.get_sub_agent_ids", new=AsyncMock(return_value={31})):
        result = await taskService.create_task(
            team_id=1,
            creator_id=20,
            title="assign task",
            assignee_id=99,
        )

    assert result["success"] is False
    assert result["error_code"] == "assignee_not_allowed"
    task_manager_mock.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_create_task_invalid_priority_returns_failure(task_manager_mock):
    result = await taskService.create_task(
        team_id=1,
        creator_id=11,
        title="bad priority",
        assignee_id=11,
        priority="urgent",
    )

    assert result["success"] is False
    assert "无效的优先级" in result["message"]
    task_manager_mock.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_create_task_depends_on_non_existent_tasks_returns_failure(task_manager_mock):
    """依赖任务缺失时不应创建。"""
    task_manager_mock.get_tasks_by_ids = AsyncMock(return_value=[])

    result = await taskService.create_task(
        team_id=1,
        creator_id=11,
        title="dep task",
        assignee_id=11,
        depends_on=[100, 101],
    )

    assert result["success"] is False
    assert "依赖任务不存在" in result["message"]
    task_manager_mock.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_create_task_with_valid_depends_on_sets_pending_status(task_manager_mock, saved_task):
    """依赖存在但未完成时，初始状态应为 PENDING。"""
    dep_task = _build_task(id=7, team_id=1, status=TaskStatus.IN_PROGRESS)
    task_manager_mock.get_tasks_by_ids = AsyncMock(return_value=[dep_task])
    task_manager_mock.create_task = AsyncMock(return_value=saved_task)

    result = await taskService.create_task(
        team_id=1,
        creator_id=11,
        title="dep task",
        assignee_id=11,
        depends_on=[7],
    )

    assert result["success"] is True
    created_task = task_manager_mock.create_task.await_args.args[0]
    assert created_task.depends_on == [7]
    assert created_task.status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_update_task_assignee_submits_for_review(task_manager_mock):
    """执行人可将进行中的任务提交为 REVIEWING。"""
    task = _build_task(status=TaskStatus.IN_PROGRESS, assignee_id=11, creator_id=11, manager_id=20)
    task_manager_mock.get_task = AsyncMock(return_value=task)
    task_manager_mock.update_task = AsyncMock(return_value=task)

    result = await taskService.update_task(team_id=1, caller_id=11, task_id=1, status="REVIEWING")

    assert result["success"] is True
    assert result["task"]["status"] == "REVIEWING"
    task_manager_mock.update_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_task_manager_approves_review(task_manager_mock):
    task = _build_task(status=TaskStatus.REVIEWING, assignee_id=11, creator_id=11, manager_id=20)
    task_manager_mock.get_task = AsyncMock(return_value=task)
    task_manager_mock.update_task = AsyncMock(return_value=task)

    result = await taskService.update_task(team_id=1, caller_id=20, task_id=1, status="DONE")

    assert result["success"] is True
    assert result["task"]["status"] == "DONE"


@pytest.mark.asyncio
async def test_update_task_manager_rejects_review(task_manager_mock):
    task = _build_task(status=TaskStatus.REVIEWING, assignee_id=11, creator_id=11, manager_id=20)
    task_manager_mock.get_task = AsyncMock(return_value=task)
    task_manager_mock.update_task = AsyncMock(return_value=task)

    result = await taskService.update_task(team_id=1, caller_id=20, task_id=1, status="IN_PROGRESS")

    assert result["success"] is True
    assert result["task"]["status"] == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_update_task_non_assignee_cannot_update(task_manager_mock):
    task = _build_task(status=TaskStatus.TODO, assignee_id=11, creator_id=11, manager_id=None)
    task_manager_mock.get_task = AsyncMock(return_value=task)

    result = await taskService.update_task(team_id=1, caller_id=12, task_id=1, status="IN_PROGRESS")

    assert result["success"] is False
    assert result["error_code"] == "permission_denied"


@pytest.mark.asyncio
async def test_update_task_invalid_state_transition_returns_failure(task_manager_mock):
    task = _build_task(status=TaskStatus.DONE, assignee_id=11, creator_id=11)
    task_manager_mock.get_task = AsyncMock(return_value=task)

    result = await taskService.update_task(team_id=1, caller_id=11, task_id=1, status="TODO")

    assert result["success"] is False
    assert result["error_code"] == "invalid_transition"


@pytest.mark.asyncio
async def test_update_task_pending_to_in_progress_blocked_by_unfinished_dependency(task_manager_mock):
    task = _build_task(status=TaskStatus.PENDING, assignee_id=11, creator_id=11, depends_on=[7])
    dep_task = _build_task(id=7, status=TaskStatus.IN_PROGRESS)
    task_manager_mock.get_task = AsyncMock(return_value=task)
    task_manager_mock.get_tasks_by_ids = AsyncMock(return_value=[dep_task])

    result = await taskService.update_task(team_id=1, caller_id=11, task_id=1, status="IN_PROGRESS")

    assert result["success"] is False
    assert result["error_code"] == "dependency_not_met"


@pytest.mark.asyncio
async def test_update_task_pending_to_in_progress_allowed_when_dependency_done(task_manager_mock):
    task = _build_task(status=TaskStatus.PENDING, assignee_id=11, creator_id=11, depends_on=[7])
    dep_task = _build_task(id=7, status=TaskStatus.DONE)
    task_manager_mock.get_task = AsyncMock(return_value=task)
    task_manager_mock.get_tasks_by_ids = AsyncMock(return_value=[dep_task])
    task_manager_mock.update_task = AsyncMock(return_value=task)

    result = await taskService.update_task(team_id=1, caller_id=11, task_id=1, status="IN_PROGRESS")

    assert result["success"] is True
    assert result["task"]["status"] == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_update_task_invalid_status_string_returns_failure(task_manager_mock):
    result = await taskService.update_task(team_id=1, caller_id=11, task_id=1, status="not-a-status")

    assert result["success"] is False
    assert "无效的状态" in result["message"]
    task_manager_mock.get_task.assert_not_called()


@pytest.mark.asyncio
async def test_update_task_not_found_returns_failure(task_manager_mock):
    task_manager_mock.get_task = AsyncMock(return_value=None)

    result = await taskService.update_task(team_id=1, caller_id=11, task_id=999, status="IN_PROGRESS")

    assert result["success"] is False
    assert "任务不存在" in result["message"]


@pytest.mark.asyncio
async def test_update_task_different_team_returns_failure(task_manager_mock):
    task = _build_task(team_id=2, assignee_id=11, creator_id=11)
    task_manager_mock.get_task = AsyncMock(return_value=task)

    result = await taskService.update_task(team_id=1, caller_id=11, task_id=1, status="IN_PROGRESS")

    assert result["success"] is False
    assert "任务不属于当前团队" in result["message"]


@pytest.mark.asyncio
async def test_update_task_assignee_cannot_cancel(task_manager_mock):
    task = _build_task(status=TaskStatus.TODO, assignee_id=11, creator_id=30, manager_id=20)
    task_manager_mock.get_task = AsyncMock(return_value=task)

    result = await taskService.update_task(team_id=1, caller_id=11, task_id=1, status="CANCELLED")

    assert result["success"] is False
    assert result["error_code"] == "permission_denied"


@pytest.mark.asyncio
async def test_update_task_manager_can_cancel(task_manager_mock):
    task = _build_task(status=TaskStatus.TODO, assignee_id=11, creator_id=30, manager_id=20)
    task_manager_mock.get_task = AsyncMock(return_value=task)
    task_manager_mock.update_task = AsyncMock(return_value=task)

    result = await taskService.update_task(team_id=1, caller_id=20, task_id=1, status="CANCELLED")

    assert result["success"] is True
    assert result["task"]["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_get_task_success_returns_task_dict(task_manager_mock):
    task = _build_task(id=1, team_id=1, title="main task", depends_on=[7])
    dep_task = _build_task(id=7, title="dep task", status=TaskStatus.DONE)
    task_manager_mock.get_task = AsyncMock(return_value=task)
    task_manager_mock.get_tasks_by_ids = AsyncMock(return_value=[dep_task])

    result = await taskService.get_task(team_id=1, task_id=1)

    assert result["success"] is True
    assert result["task"]["id"] == 1
    assert result["task"]["depends_on_details"] == [{"task_id": 7, "title": "dep task", "status": "DONE"}]


@pytest.mark.asyncio
async def test_get_task_not_found_returns_failure(task_manager_mock):
    task_manager_mock.get_task = AsyncMock(return_value=None)

    result = await taskService.get_task(team_id=1, task_id=1)

    assert result["success"] is False
    assert "任务不存在" in result["message"]


@pytest.mark.asyncio
async def test_get_task_wrong_team_returns_failure(task_manager_mock):
    task_manager_mock.get_task = AsyncMock(return_value=_build_task(team_id=2))

    result = await taskService.get_task(team_id=1, task_id=1)

    assert result["success"] is False
    assert "任务不属于当前团队" in result["message"]


@pytest.mark.asyncio
async def test_list_tasks_basic_call_returns_tasks(task_manager_mock):
    tasks = [
        _build_task(id=1, title="task 1", status=TaskStatus.TODO),
        _build_task(id=2, title="task 2", status=TaskStatus.DONE),
    ]
    task_manager_mock.list_tasks = AsyncMock(return_value=tasks)

    result = await taskService.list_tasks(team_id=1)

    assert result["success"] is True
    assert result["total"] == 2
    assert [task["id"] for task in result["tasks"]] == [1, 2]
    task_manager_mock.list_tasks.assert_awaited_once_with(
        team_id=1,
        assignee_id=None,
        manager_id=None,
        status=None,
        exclude_statuses=None,
        limit=20,
    )


@pytest.mark.asyncio
async def test_create_task_publishes_task_created_event(task_manager_mock, saved_task):
    """创建任务成功时应发布 TASK_CREATED 事件。"""
    task_manager_mock.create_task = AsyncMock(return_value=saved_task)

    with patch("service.messageBus.publish") as mock_publish:
        result = await taskService.create_task(
            team_id=1,
            creator_id=11,
            title="broadcast test",
            assignee_id=11,
        )

    assert result["success"] is True
    mock_publish.assert_called_once()
    topic = mock_publish.call_args.args[0]
    assert topic.name == "TASK_CREATED"
    assert mock_publish.call_args.kwargs["task"] is saved_task


@pytest.mark.asyncio
async def test_update_task_publishes_task_changed_event(task_manager_mock):
    """更新任务状态成功时应发布 TASK_CHANGED 事件并携带 old_status。"""
    task = _build_task(status=TaskStatus.IN_PROGRESS, assignee_id=11, creator_id=11, manager_id=20)
    task_manager_mock.get_task = AsyncMock(return_value=task)
    task_manager_mock.update_task = AsyncMock(return_value=task)

    with patch("service.messageBus.publish") as mock_publish:
        result = await taskService.update_task(team_id=1, caller_id=11, task_id=1, status="REVIEWING")

    assert result["success"] is True
    mock_publish.assert_called_once()
    topic = mock_publish.call_args.args[0]
    assert topic.name == "TASK_CHANGED"
    assert mock_publish.call_args.kwargs["task"] is task
    assert mock_publish.call_args.kwargs["old_status"] == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_create_task_does_not_publish_on_failure(task_manager_mock):
    """创建任务失败时不应发布任何事件。"""
    with patch("service.messageBus.publish") as mock_publish:
        result = await taskService.create_task(
            team_id=1,
            creator_id=11,
            title="bad priority",
            assignee_id=11,
            priority="urgent",
        )

    assert result["success"] is False
    mock_publish.assert_not_called()


@pytest.mark.asyncio
async def test_update_task_does_not_publish_on_failure(task_manager_mock):
    """更新任务失败时不应发布任何事件。"""
    task_manager_mock.get_task = AsyncMock(return_value=None)

    with patch("service.messageBus.publish") as mock_publish:
        result = await taskService.update_task(team_id=1, caller_id=11, task_id=999, status="IN_PROGRESS")

    assert result["success"] is False
    mock_publish.assert_not_called()


@pytest.mark.asyncio
async def test_list_tasks_open_only_excludes_done_and_cancelled(task_manager_mock):
    task_manager_mock.list_tasks = AsyncMock(return_value=[_build_task(id=3, status=TaskStatus.IN_PROGRESS)])

    result = await taskService.list_tasks(team_id=1, assignee_id=11, open_only=True, limit=10)

    assert result["success"] is True
    assert result["total"] == 1
    task_manager_mock.list_tasks.assert_awaited_once_with(
        team_id=1,
        assignee_id=11,
        manager_id=None,
        status=None,
        exclude_statuses=[TaskStatus.DONE, TaskStatus.CANCELLED],
        limit=10,
    )
