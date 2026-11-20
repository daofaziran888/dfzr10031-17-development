"""数据API发布接口：维护数据服务，并支持按服务的输出数据集与查询参数做批量交付。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.data_service import POLICY_CONFIRMED, POLICIES, DataServiceService

router = APIRouter(prefix="/api/data_service", tags=["数据API发布"])

service = DataServiceService()

LIST_FIELDS = ["服务编号", "服务名称", "输出数据集", "查询参数", "响应字段", "缓存秒数", "分页上限", "服务状态"]
STATUSES = ["草稿", "已配置", "已发布", "已停用"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出数据API发布清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "data_service", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按服务编号检索"),
    status: str | None = Query(default=None, description="草稿、已配置、已发布、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按服务编号与状态过滤数据API发布列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    extra = {k: v for k, v in request.query_params.items() if k not in ("keyword", "status", "page", "size") and v.strip()}
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size, extra=extra)
    return PageResult(items=items, total=total, page=page, size=size)


# ---- 批量交付 ---------------------------------------------------------
# 注意：交付相关路由要写在 /{entry_id} 之前，否则 "deliveries" 会被当成数字 id。


@router.get("/deliveries")
def list_deliveries() -> dict[str, Any]:
    """列出批量交付记录，最近的在前。"""
    items = service.list_deliveries()
    return {"items": items, "total": len(items)}


@router.get("/snapshots")
def list_snapshots() -> dict[str, Any]:
    """列出各输出数据集当前可用的数据截面及确认状态。"""
    items = service.list_snapshots()
    return {"items": items, "total": len(items), "policies": POLICIES}


@router.post("/snapshots/{snapshot_no}/confirm", response_model=ActionResult)
def confirm_snapshot(snapshot_no: str) -> ActionResult:
    """服务确认某个数据截面，确认后「已确认一致」策略可选用。"""
    snapshot, message = service.confirm_snapshot(snapshot_no)
    if snapshot is None:
        return ActionResult(ok=False, message=message)
    summary = {key: val for key, val in snapshot.items() if key != "明细"}
    return ActionResult(ok=True, message=message, entry=summary)


@router.get("/deliveries/{delivery_no}")
def get_delivery(delivery_no: str) -> dict[str, Any]:
    """按交付编号回放当时的明细、金额与取数边界，不重新访问源数据。"""
    detail = service.get_delivery_detail(delivery_no)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"交付 {delivery_no} 不存在")
    return detail


@router.get("/deliveries/{delivery_no}/reconcile")
def reconcile_delivery(delivery_no: str) -> dict[str, Any]:
    """复核交付：留存明细与当前源数据逐条比对，列出差异。"""
    result = service.reconcile(delivery_no)
    if result is None:
        raise HTTPException(status_code=404, detail=f"交付 {delivery_no} 不存在")
    return result


@router.post("/deliveries", response_model=ActionResult)
def create_delivery(payload: EntryPayload) -> ActionResult:
    """发起批量交付：按服务输出数据集与查询参数取截面明细，任一服务缺截面则挂起补取。"""
    values = payload.values
    services = values.get("服务编号") or values.get("services") or []
    if isinstance(services, str):
        services = [item for item in services.replace("，", ",").split(",") if item.strip()]
    params = values.get("查询参数") or values.get("params") or {}
    policy = str(values.get("截面策略") or values.get("policy") or POLICY_CONFIRMED)
    delivery, message = service.create_delivery(list(services), dict(params), policy)
    if delivery is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=delivery.get("状态") == "已交付", message=message, entry=delivery)


@router.post("/deliveries/{delivery_no}/retry", response_model=ActionResult)
def retry_delivery(delivery_no: str) -> ActionResult:
    """对挂起交付按原截面策略补取；仍缺截面时保持挂起。"""
    delivery, message = service.retry_delivery(delivery_no)
    if delivery is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=delivery.get("状态") == "已交付", message=message, entry=delivery)


@router.post("/source/{dataset}/corrections", response_model=ActionResult)
def correct_source(dataset: str, payload: EntryPayload) -> ActionResult:
    """更正源数据中的一笔金额，并生成待确认截面（不覆盖已确认截面）。"""
    values = payload.values
    doc_no = str(values.get("单据号") or values.get("doc_no") or "").strip()
    field = str(values.get("字段") or values.get("field") or "").strip()
    snapshot, message = service.correct_source(
        dataset, doc_no, field, values.get("金额", values.get("value"))
    )
    if snapshot is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=snapshot)


# ---- 单条服务 ---------------------------------------------------------


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条数据服务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"数据服务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条数据服务，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="数据服务已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条数据服务执行保存配置、发布服务、停用服务；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
