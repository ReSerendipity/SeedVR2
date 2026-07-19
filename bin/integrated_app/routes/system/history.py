"""历史记录 API 路由"""

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
    """获取历史记录列表"""
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
    """获取历史记录表格 HTML 片段（用于 HTMX 局部刷新）"""
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
    """获取历史统计"""
    return await history_db.get_statistics()


@router.delete("/{record_id}")
async def delete_history_record(record_id: int, history_db: HistoryDB = Depends(get_history_db)):
    """删除历史记录"""
    success = await history_db.delete_record(record_id)
    return {"success": success}


@router.post("/{record_id}/cancel")
async def cancel_history_record(
    record_id: int,
    history_db: HistoryDB = Depends(get_history_db),
    task_queue: TaskQueue = Depends(get_task_queue),
):
    """取消历史记录关联的进行中任务"""
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
    """清除历史记录"""
    count = await history_db.clear_records(before_date)
    return {"deleted_count": count}
