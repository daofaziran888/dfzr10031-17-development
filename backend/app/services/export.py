"""数据导出业务规则：导出任务流转，以及按批量交付编号交付记录及其关联依据。"""
from __future__ import annotations

from typing import Any

from app.services.data_service import DataServiceService, _fmt_amount as fmt_amount, _now
from app.store import store

MODULE = "export"
DELIVERY_PACKAGE_MODULE = "export_delivery_package"
REQUIRED_FIELDS = ["任务编号", "导出对象", "导出格式"]
STATUS_ORDER = ["待导出", "导出中", "已完成", "导出失败"]
ACTION_RULES = {"开始导出": "导出中", "重新导出": "待导出", "标记失败": "导出失败"}
NEGATIVE_ACTIONS = []


class ExportService:
    def __init__(self) -> None:
        self.deliveries = DataServiceService()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        extra: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if extra:
            for field, val in extra.items():
                rows = [row for row in rows if val in str(row.get(field, ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"导出任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据导出可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"导出任务已{action}"

    # ------------------------------------------------------------------
    # 按交付编号交付：记录 + 关联依据
    # ------------------------------------------------------------------
    def list_packages(self) -> list[dict[str, Any]]:
        rows = store.rows(DELIVERY_PACKAGE_MODULE)
        return sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)

    def get_package(self, delivery_no: str) -> dict[str, Any] | None:
        for row in store.rows(DELIVERY_PACKAGE_MODULE):
            if row.get("交付编号") == delivery_no:
                return row
        return None

    def file_delivery(
        self, delivery_no: str, export_format: str = "Excel"
    ) -> tuple[dict[str, Any] | None, str]:
        """把一次批量交付落成导出包：每条记录连同其关联依据一起交付。"""
        delivery_no = str(delivery_no or "").strip()
        if not delivery_no:
            return None, "请填写要交付的批量交付编号"
        detail = self.deliveries.get_delivery_detail(delivery_no)
        if detail is None:
            return None, f"交付 {delivery_no} 不存在"
        if detail.get("状态") != "已交付":
            return None, f"交付 {delivery_no} 当前为{detail.get('状态')}，补齐截面后才能交付"

        lines = detail.get("明细") or []
        orders = [line for line in lines if line.get("输出数据集") == "订单"]
        refunds = [line for line in lines if line.get("输出数据集") == "退款"]
        order_nos = {str(line["明细"].get("订单号")) for line in orders}
        records: list[dict[str, Any]] = []
        for line in orders:
            linked = [
                {
                    "退款单号": item["明细"].get("退款单号"),
                    "退款金额": item["明细"].get("退款金额"),
                    "基准": "原订单号",
                }
                for item in refunds
                if str(item["明细"].get("原订单号")) == str(line["明细"].get("订单号"))
            ]
            records.append({
                "记录类型": "订单",
                "单据号": line["明细"].get("订单号"),
                "记账金额": line.get("记账金额"),
                "记账金额文本": fmt_amount(line.get("记账金额")),
                "记录": line["明细"],
                "取数边界": line.get("取数边界"),
                "关联依据": linked,
            })
        for line in refunds:
            origin = str(line["明细"].get("原订单号") or "")
            records.append({
                "记录类型": "退款",
                "单据号": line["明细"].get("退款单号"),
                "记账金额": line.get("记账金额"),
                "记账金额文本": fmt_amount(line.get("记账金额")),
                "记录": line["明细"],
                "取数边界": line.get("取数边界"),
                "关联依据": [{
                    "订单号": origin,
                    "关联状态": "已关联原订单" if origin in order_nos else "孤立退款，未找到原订单",
                }],
            })

        rows = store.rows(DELIVERY_PACKAGE_MODULE)
        entry = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "交付编号": delivery_no,
            "导出格式": export_format or "Excel",
            "导出时间": _now(),
            "交付时交付状态": detail.get("状态"),
            "截面策略": detail.get("截面策略"),
            "记录条数": len(records),
            "订单合计": detail.get("订单合计"),
            "退款合计": detail.get("退款合计"),
            "核对": detail.get("核对"),
            "记录": records,
        }
        # 同一交付编号重复导出时更新当次包，交付内容仍以交付快照为准。
        existing = self.get_package(delivery_no)
        if existing is not None:
            entry["id"] = existing["id"]
            existing.clear()
            existing.update(entry)
            entry = existing
        else:
            rows.append(entry)
        return entry, f"交付 {delivery_no} 已生成导出包，共 {len(records)} 条记录及其关联依据"

    def delete_package(self, delivery_no: str) -> bool:
        package = self.get_package(delivery_no)
        if package is None:
            return False
        store.rows(DELIVERY_PACKAGE_MODULE).remove(package)
        return True
