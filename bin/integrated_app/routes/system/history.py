#!/usr/bin/env python3
"""历史记录管理路由模块。

提供修复历史记录的查询、统计、删除、取消等端点，
支持分页、筛选、全文搜索，并提供 HTMX 表格局部刷新端点。

API 端点：
- GET /api/system/history: 获取历史记录列表（JSON）
- GET /api/system/history/table: 获取历史记录表格 HTML（HTMX）
- GET /api/system/history/statistics: 获取历史统计数据
- DELETE /api/system/history/{record_id}: 删除单条历史记录
- POST /api/system/history/{record_id}/cancel: 取消关联的进行中任务
- DELETE /api/system/history: 批量清除历史记录

注意：本模块 router 已自带 prefix="/history"，实际路径为 /api/system/history/*

所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from bin.integrated_app.dependencies import get_history_db, get_jinja_env, get_task_queue
from bin.integrated_app.history_db import HistoryDB
from bin.integrated_app.task_queue import TaskQueue

router = APIRouter(prefix="/history", tags=["history"])


@router.get("")
async def get_history(
    history_db: HistoryDB = Depends(get_history_db),
    task_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """获取历史记录列表（JSON 格式）。

    API 端点：GET /api/system/history

    查询参数：
    - task_type (optional): 按任务类型筛选，"image"/"video"
    - status (optional): 按状态筛选，"pending"/"processing"/"completed"/"failed"/"cancelled"
    - search (optional): 全文搜索关键词
    - page (optional): 页码，默认 1，最小 1
    - page_size (optional): 每页条数，默认 20，范围 1-100

    返回格式（JSON）：
    {
        "records": [ ... ],     // 历史记录列表（使用 vars() 序列化）
        "total": int,           // 总记录数
        "page": int,
        "page_size": int,
        "total_pages": int
    }

    Args:
        history_db: 历史数据库实例（通过依赖注入）。
        task_type: 任务类型筛选。
        status: 状态筛选。
        search: 搜索关键词。
        page: 页码。
        page_size: 每页条数。

    Returns:
        包含历史记录和分页信息的字典。
    """
    if search:
        records, total = await history_db.search_records(
            query=search, limit=page_size, offset=(page - 1) * page_size
        )
    else:
        records, total = await history_db.get_records(
            task_type=task_type, status=status,
            limit=page_size, offset=(page - 1) * page_size
        )

    return {
        "records": [vars(r) for r in records],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/table")
async def get_history_table(
    request: Request,
    history_db: HistoryDB = Depends(get_history_db),
    task_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """获取历史记录表格 HTML 片段（用于 HTMX 局部刷新）。

    API 端点：GET /api/system/history/table

    查询参数与 get_history 相同。返回渲染后的 HTML 片段，
    供 HTMX 直接替换页面中的表格区域，无需整页刷新。

    Args:
        request: FastAPI 请求对象。
        history_db: 历史数据库实例（通过依赖注入）。
        task_type: 任务类型筛选。
        status: 状态筛选。
        search: 搜索关键词。
        page: 页码。
        page_size: 每页条数。

    Returns:
        HTMLResponse 包含渲染后的表格片段。
    """
    if search:
        records, total = await history_db.search_records(
            query=search, limit=page_size, offset=(page - 1) * page_size
        )
    else:
        records, total = await history_db.get_records(
            task_type=task_type, status=status,
            limit=page_size, offset=(page - 1) * page_size
        )

    env = get_jinja_env(request)
    template = env.get_template("history_table.html")
    html = template.render(records=records, total=total, t=request.app.state.i18n.t)
    return HTMLResponse(content=html)


@router.get("/statistics")
async def get_statistics(history_db: HistoryDB = Depends(get_history_db)):
    """获取历史记录统计数据。

    API 端点：GET /api/system/history/statistics

    请求参数：无

    返回格式（JSON）：由 history_db.get_statistics() 返回的统计信息字典，
    包含总任务数、成功/失败/取消计数等。

    Args:
        history_db: 历史数据库实例（通过依赖注入）。

    Returns:
        统计数据字典。
    """
    return await history_db.get_statistics()


@router.delete("/{record_id}")
async def delete_history_record(record_id: int, history_db: HistoryDB = Depends(get_history_db)):
    """删除单条历史记录。

    API 端点：DELETE /api/system/history/{record_id}

    路径参数：
    - record_id: 历史记录 ID

    返回格式（JSON）：
    {
        "success": bool
    }

    Args:
        record_id: 要删除的记录 ID。
        history_db: 历史数据库实例（通过依赖注入）。

    Returns:
        包含删除结果的字典。
    """
    success = await history_db.delete_record(record_id)
    return {"success": success}


@router.post("/{record_id}/cancel")
async def cancel_history_record(
    record_id: int,
    history_db: HistoryDB = Depends(get_history_db),
    task_queue: TaskQueue = Depends(get_task_queue),
):
    """取消历史记录关联的进行中任务。

    API 端点：POST /api/system/history/{record_id}/cancel

    路径参数：
    - record_id: 历史记录 ID

    返回格式（JSON）：
    {
        "success": true,
        "task_id": str,
        "status": "cancelled"
    }

    错误响应：
    - 404: 记录不存在或未找到关联任务
    - 400: 记录状态不允许取消

    Args:
        record_id: 历史记录 ID。
        history_db: 历史数据库实例（通过依赖注入）。
        task_queue: 任务队列实例（通过依赖注入）。

    Returns:
        取消操作结果。

    Raises:
        HTTPException: 记录不存在、状态非法或无关联任务时抛出。
    """
    record = await history_db.get_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    if record.status not in ("pending", "processing"):
        raise HTTPException(status_code=400, detail=f"记录状态为 {record.status}，无法取消")

    task = await history_db.get_task_by_record_id(record_id)
    if not task:
        raise HTTPException(status_code=404, detail="未找到关联任务")

    task_queue.request_cancel(task.task_id)
    await history_db.update_task(task.task_id, status="cancelled", error_message="用户取消")
    await history_db.update_record(record_id, status="cancelled", error_message="用户取消")
    return {"success": True, "task_id": task.task_id, "status": "cancelled"}


@router.delete("")
async def clear_history(
    before_date: str | None = None,
    history_db: HistoryDB = Depends(get_history_db),
):
    """批量清除历史记录。

    API 端点：DELETE /api/system/history

    查询参数：
    - before_date (optional): 清除此日期之前的记录，格式由数据库层解析；
      不提供则清除所有记录。

    返回格式（JSON）：
    {
        "deleted_count": int  // 被删除的记录数
    }

    Args:
        before_date: 截止日期，可选。
        history_db: 历史数据库实例（通过依赖注入）。

    Returns:
        包含删除数量的字典。
    """
    count = await history_db.clear_records(before_date)
    return {"deleted_count": count}
