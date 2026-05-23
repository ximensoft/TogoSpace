"""协作任务管理服务。

负责任务的创建、状态流转、权限校验和查询逻辑。
"""

from __future__ import annotations

import logging
from typing import Optional
from typing import Any

from constants import TaskPriority, TaskStatus
from dal.db import gtAgentTaskManager
from model.dbModel.gtAgentTask import GtAgentTask

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 合法状态流转表
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.TODO:        {TaskStatus.IN_PROGRESS, TaskStatus.PENDING, TaskStatus.CANCELLED},
    TaskStatus.PENDING:     {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
    TaskStatus.IN_PROGRESS: {TaskStatus.REVIEWING, TaskStatus.DONE, TaskStatus.ON_HOLD, TaskStatus.CANCELLED},
    TaskStatus.REVIEWING:   {TaskStatus.DONE, TaskStatus.IN_PROGRESS},
    TaskStatus.ON_HOLD:     {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
    TaskStatus.DONE:        set(),
    TaskStatus.CANCELLED:   set(),
}


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------

async def create_task(
    team_id: int,
    creator_id: int,
    title: str,
    assignee_id: int,
    description: str = '',
    manager_id: Optional[int] = None,
    priority: str = 'NORMAL',
    parent_id: Optional[int] = None,
    depends_on: Optional[list[int]] = None,
    room_id: Optional[int] = None,
) -> dict:
    """创建协作任务。

    Returns:
        dict with keys: success, task_id (on success) or message (on failure)
    """
    priority_enum = TaskPriority.value_of(priority.upper())
    if priority_enum is None:
        return {"success": False, "message": f"无效的优先级：{priority}，有效值为 HIGH / NORMAL / LOW"}

    # 验证 assignee 权限
    if assignee_id != creator_id:
        from service import deptService
        subordinates = await deptService.get_sub_agent_ids(team_id, creator_id)
        if assignee_id not in subordinates:
            return {
                "success": False,
                "message": f"无权将任务分配给 agent_id={assignee_id}，只能分配给自己或直接/间接下属",
                "error_code": "assignee_not_allowed",
            }

    # 验证并解析依赖
    dep_ids: list[int] = list(depends_on or [])
    initial_status = TaskStatus.TODO
    if dep_ids:
        dep_tasks = await gtAgentTaskManager.get_tasks_by_ids(dep_ids)
        found_ids = {t.id for t in dep_tasks}
        missing = [d for d in dep_ids if d not in found_ids]
        if missing:
            return {"success": False, "message": f"依赖任务不存在：{missing}"}
        wrong_team = [t.id for t in dep_tasks if t.team_id != team_id]
        if wrong_team:
            return {"success": False, "message": f"依赖任务不属于当前团队：{wrong_team}"}
        if any(t.status != TaskStatus.DONE for t in dep_tasks):
            initial_status = TaskStatus.PENDING

    task = GtAgentTask(
        team_id=team_id,
        title=title,
        description=description,
        assignee_id=assignee_id,
        creator_id=creator_id,
        manager_id=manager_id,
        status=initial_status,
        priority=priority_enum,
        parent_id=parent_id,
        depends_on=dep_ids,
        room_id=room_id,
        result='',
        block_reason='',
    )
    saved = await gtAgentTaskManager.create_task(task)
    logger.info(f"任务创建：task_id={saved.id}, title={title!r}, assignee={assignee_id}, status={initial_status.value}")
    return {"success": True, "task_id": saved.id, "message": f"任务已创建，task_id={saved.id}，状态={initial_status.value}"}


async def update_task(
    team_id: int,
    caller_id: int,
    task_id: int,
    status: str,
    result: str = '',
    block_reason: str = '',
) -> dict:
    """更新协作任务状态。

    Returns:
        dict with keys: success, task (on success) or message (on failure)
    """
    new_status = TaskStatus.value_of(status.upper())
    if new_status is None:
        return {"success": False, "message": f"无效的状态：{status}"}

    task = await gtAgentTaskManager.get_task(task_id)
    if task is None:
        return {"success": False, "message": f"任务不存在：task_id={task_id}"}
    if task.team_id != team_id:
        return {"success": False, "message": "任务不属于当前团队"}

    old_status = task.status
    is_assignee = (caller_id == task.assignee_id)
    is_manager  = (task.manager_id is not None and caller_id == task.manager_id) or (task.manager_id is None and caller_id == task.creator_id)
    is_creator  = (caller_id == task.creator_id)

    # 权限校验
    if new_status == TaskStatus.REVIEWING:
        if not is_assignee:
            return {"success": False, "message": "只有执行人（assignee）才能提交验收", "error_code": "permission_denied"}
    elif new_status == TaskStatus.DONE and old_status == TaskStatus.REVIEWING:
        if not is_manager:
            return {"success": False, "message": "只有验收人（manager）才能通过验收", "error_code": "permission_denied"}
    elif new_status == TaskStatus.IN_PROGRESS and old_status == TaskStatus.REVIEWING:
        if not is_manager:
            return {"success": False, "message": "只有验收人（manager）才能打回任务", "error_code": "permission_denied"}
    elif new_status == TaskStatus.CANCELLED:
        if not is_manager and not is_creator:
            return {"success": False, "message": "只有验收人或创建人才能取消任务", "error_code": "permission_denied"}
    else:
        if not is_assignee:
            return {"success": False, "message": "只有执行人（assignee）才能更新任务状态", "error_code": "permission_denied"}

    # 状态流转合法性
    if new_status not in _VALID_TRANSITIONS.get(old_status, set()):
        return {
            "success": False,
            "message": f"不允许的状态流转：{old_status.value} → {new_status.value}",
            "error_code": "invalid_transition",
        }

    # 依赖检查
    if old_status == TaskStatus.PENDING and new_status == TaskStatus.IN_PROGRESS:
        if task.depends_on:
            dep_tasks = await gtAgentTaskManager.get_tasks_by_ids(task.depends_on)
            unfinished = [t.id for t in dep_tasks if t.status != TaskStatus.DONE]
            if unfinished:
                return {
                    "success": False,
                    "message": f"存在未完成的依赖任务，无法开始：{unfinished}",
                    "error_code": "dependency_not_met",
                }

    # 有 manager 时，IN_PROGRESS 不能直接 → DONE
    if new_status == TaskStatus.DONE and old_status == TaskStatus.IN_PROGRESS and task.manager_id is not None:
        return {
            "success": False,
            "message": "该任务设有验收人，请先提交验收（status=REVIEWING），由验收人审核后完成",
            "error_code": "review_required",
        }

    # 执行更新
    fields: list[Any] = [GtAgentTask.status]
    task.status = new_status
    if result:
        task.result = result
        fields.append(GtAgentTask.result)
    if block_reason:
        task.block_reason = block_reason
        fields.append(GtAgentTask.block_reason)

    updated = await gtAgentTaskManager.update_task(task, fields)
    logger.info(f"任务状态变更：task_id={task_id}, {old_status.value} → {new_status.value}, caller={caller_id}")

    from playhouse.shortcuts import model_to_dict
    return {"success": True, "task": model_to_dict(updated, recurse=False), "message": f"任务状态已更新：{old_status.value} → {new_status.value}"}


async def get_task(team_id: int, task_id: int) -> dict:
    """查询单个任务详情，含依赖任务状态摘要。"""
    from playhouse.shortcuts import model_to_dict

    task = await gtAgentTaskManager.get_task(task_id)
    if task is None:
        return {"success": False, "message": f"任务不存在：task_id={task_id}"}
    if task.team_id != team_id:
        return {"success": False, "message": "任务不属于当前团队"}

    task_dict = model_to_dict(task, recurse=False)

    depends_on_details: list[dict] = []
    if task.depends_on:
        dep_tasks = await gtAgentTaskManager.get_tasks_by_ids(task.depends_on)
        dep_map = {t.id: t for t in dep_tasks}
        for dep_id in task.depends_on:
            dep = dep_map.get(dep_id)
            if dep:
                depends_on_details.append({"task_id": dep.id, "title": dep.title, "status": dep.status.value})
            else:
                depends_on_details.append({"task_id": dep_id, "title": "(已删除)", "status": "UNKNOWN"})
    task_dict["depends_on_details"] = depends_on_details

    return {"success": True, "task": task_dict}


async def list_tasks(
    team_id: int,
    assignee_id: Optional[int] = None,
    manager_id: Optional[int] = None,
    status: Optional[str] = None,
    open_only: bool = False,
    limit: int = 20,
) -> dict:
    """查询协作任务列表。"""
    from playhouse.shortcuts import model_to_dict

    status_enum: Optional[TaskStatus] = None
    exclude_statuses: list[TaskStatus] | None = None
    if status is not None:
        status_enum = TaskStatus.value_of(status.upper())
        if status_enum is None:
            return {"success": False, "message": f"无效的状态：{status}"}
    elif open_only:
        exclude_statuses = [TaskStatus.DONE, TaskStatus.CANCELLED]

    tasks = await gtAgentTaskManager.list_tasks(
        team_id=team_id,
        assignee_id=assignee_id,
        manager_id=manager_id,
        status=status_enum,
        exclude_statuses=exclude_statuses,
        limit=limit,
    )
    return {"success": True, "tasks": [model_to_dict(t, recurse=False) for t in tasks], "total": len(tasks)}
