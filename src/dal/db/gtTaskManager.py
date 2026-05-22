from __future__ import annotations

import datetime

from constants import TaskStatus
from model.dbModel.gtTask import GtTask


async def create_task(task: GtTask) -> GtTask:
    """保存新任务，返回含主键的实例。"""
    await task.aio_save(force_insert=True)
    return task


async def get_task(task_id: int) -> GtTask | None:
    """按主键查询任务。"""
    return await GtTask.aio_get_or_none(GtTask.id == task_id)


async def list_tasks(
    team_id: int,
    assignee_id: int | None = None,
    manager_id: int | None = None,
    status: TaskStatus | None = None,
    limit: int = 20,
) -> list[GtTask]:
    """按条件查询任务列表，按创建时间降序。"""
    query = GtTask.select().where(GtTask.team_id == team_id)
    if assignee_id is not None:
        query = query.where(GtTask.assignee_id == assignee_id)
    if manager_id is not None:
        query = query.where(GtTask.manager_id == manager_id)
    if status is not None:
        query = query.where(GtTask.status == status)
    query = query.order_by(GtTask.id.desc()).limit(limit)
    return list(await query.aio_execute())


async def get_tasks_by_ids(task_ids: list[int]) -> list[GtTask]:
    """批量查询任务（用于依赖状态检查）。"""
    if not task_ids:
        return []
    return list(
        await GtTask.select()
        .where(GtTask.id.in_(task_ids))  # type: ignore[attr-defined]
        .aio_execute()
    )


async def update_task(task: GtTask, fields: list) -> GtTask:
    """更新指定字段，同时刷新 updated_at。"""
    task.updated_at = datetime.datetime.now()
    if GtTask.updated_at not in fields:
        fields = list(fields) + [GtTask.updated_at]
    await task.aio_save(only=fields)
    return task
