"""数据服务批量交付：按服务输出数据集与查询参数取截面明细，供数据导出按交付编号留存与复查。

约定（与财务对账口径一致）：
- 实付金额按订单记账，同一订单关联多张退款单时实付只累计一次；
- 退款金额按退款单记账，找不到原订单的退款仍计入退款合计，并单独列入孤立退款；
- 一次交付只采用一种截面口径：`已确认一致` 或 `最新重取`，不允许两口径混用；
- 交付明细落 `data_service_delivery_line` 快照，按交付编号重开时只回放快照，不再访问源数据；
- 所需截面不足时不落半包，交付状态置为 `待补取`，补齐后可重试同一交付编号。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "data_service"
DELIVERY_MODULE = "data_service_delivery"
SNAPSHOT_MODULE = "data_service_delivery_line"
SNAPSHOT_SOURCE_MODULE = "delivery_snapshot"
ORDER_MODULE = "delivery_order"
REFUND_MODULE = "delivery_refund"

SOURCE_MODULES = {"订单": ORDER_MODULE, "退款": REFUND_MODULE}
DOC_KEY = {"订单": "订单号", "退款": "退款单号"}
AMOUNT_FIELD = {"订单": "实付金额", "退款": "退款金额"}
DATASET_PREFIX = {"订单": "ORD", "退款": "REF", "渠道": "CHN"}

POLICY_CONFIRMED = "已确认一致"
POLICY_LATEST = "最新重取"
POLICIES = [POLICY_CONFIRMED, POLICY_LATEST]
POLICY_NOTES = {
    POLICY_CONFIRMED: "只交付各服务均已确认的旧截面，口径一致但可能落后于源数据更正",
    POLICY_LATEST: "各服务均取各自最新可重取截面，交付前重新核对，允许包含待确认更正",
}

REQUIRED_FIELDS = ["服务编号", "服务名称", "输出数据集"]
STATUS_ORDER = ["草稿", "已配置", "已发布", "已停用"]
ACTION_RULES = {"保存配置": "已配置", "发布服务": "已发布", "停用服务": "已停用"}
NEGATIVE_ACTIONS = ["停用服务"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fingerprint(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _as_amount(value: Any) -> int | None:
    """金额一律折算到分，源数据可能是整数元，也可能是带小数的字符串。"""
    if value is None or value == "":
        return None
    try:
        return int(round(float(str(value).replace(",", "").strip()) * 100))
    except (TypeError, ValueError):
        return None


def _fmt_amount(cents: int | None) -> str:
    if cents is None:
        return "—"
    return f"{cents / 100:.2f}"


def _yuan(cents: int) -> float:
    return round(cents / 100, 2)


class DataServiceService:
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
            rows = [row for row in rows if keyword in str(row.get("服务编号", ""))]
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
            return None, f"数据服务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据API发布可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"数据服务已{action}"

    # ------------------------------------------------------------------
    # 截面
    # ------------------------------------------------------------------
    def list_snapshots(self) -> list[dict[str, Any]]:
        return [
            {key: val for key, val in row.items() if key != "明细"}
            for row in store.rows(SNAPSHOT_SOURCE_MODULE)
        ]

    def confirm_snapshot(self, snapshot_no: str) -> tuple[dict[str, Any] | None, str]:
        """服务确认某个截面：确认后「已确认一致」策略才会选到它。"""
        target = next(
            (
                row
                for row in store.rows(SNAPSHOT_SOURCE_MODULE)
                if row.get("截面号") == snapshot_no
            ),
            None,
        )
        if target is None:
            return None, f"截面 {snapshot_no} 不存在"
        if target.get("状态") == "已确认":
            return target, f"截面 {snapshot_no} 已是已确认状态"
        target["状态"] = "已确认"
        target["确认时间"] = _now()
        return target, f"截面 {snapshot_no} 已由服务确认"

    def _snapshots_of(self, dataset: str) -> list[dict[str, Any]]:
        rows = [
            row
            for row in store.rows(SNAPSHOT_SOURCE_MODULE)
            if row.get("数据集") == dataset
        ]
        return sorted(rows, key=lambda row: int(row.get("版本", 0)))

    def _pick_snapshot(
        self, dataset: str, policy: str
    ) -> tuple[dict[str, Any] | None, str]:
        snaps = self._snapshots_of(dataset)
        if not snaps:
            return None, f"输出数据集「{dataset}」尚无可用数据截面"
        if policy == POLICY_CONFIRMED:
            confirmed = [row for row in snaps if row.get("状态") == "已确认"]
            if not confirmed:
                return None, f"输出数据集「{dataset}」没有已确认截面"
            return confirmed[-1], ""
        return snaps[-1], ""

    def _query_snapshot(
        self, snapshot: dict[str, Any], params: dict[str, str]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows = [dict(row) for row in snapshot.get("明细", [])]
        columns = {key for row in rows for key in row}
        applied: dict[str, str] = {}
        ignored: dict[str, str] = {}
        for field, val in params.items():
            val = str(val).strip()
            if not val or field in ("开始日期", "结束日期"):
                continue
            if field not in columns:
                # 参数不是该数据集的列时明确标注未适用，而不是静默过滤成空结果。
                ignored[field] = val
                continue
            rows = [row for row in rows if val == str(row.get(field, ""))]
            applied[field] = val
        start = str(params.get("开始日期") or "").strip()
        end = str(params.get("结束日期") or "").strip()
        if start:
            applied["开始日期"] = start
            rows = [row for row in rows if str(row.get("日期", "")) >= start]
        if end:
            applied["结束日期"] = end
            rows = [row for row in rows if str(row.get("日期", "")) <= end]
        boundary = {
            "输出数据集": snapshot.get("数据集"),
            "截面号": snapshot.get("截面号"),
            "截面版本": snapshot.get("版本"),
            "截面状态": snapshot.get("状态"),
            "查询参数": applied,
            "未适用参数": ignored,
            "命中行数": len(rows),
            "明细指纹": _fingerprint(rows),
        }
        return rows, boundary

    def _service_by_no(self, service_no: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if row.get("服务编号") == service_no:
                return row
        return None

    # ------------------------------------------------------------------
    # 批量交付
    # ------------------------------------------------------------------
    def list_deliveries(self) -> list[dict[str, Any]]:
        rows = [
            {key: val for key, val in row.items() if key not in ("核对",)}
            for row in store.rows(DELIVERY_MODULE)
        ]
        return sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)

    def get_delivery(self, delivery_no: str) -> dict[str, Any] | None:
        for row in store.rows(DELIVERY_MODULE):
            if row.get("交付编号") == delivery_no:
                return row
        return None

    def delivery_lines(self, delivery_no: str) -> list[dict[str, Any]]:
        return [
            row
            for row in store.rows(SNAPSHOT_MODULE)
            if row.get("交付编号") == delivery_no
        ]

    def create_delivery(
        self,
        service_nos: list[str],
        params: dict[str, str] | None = None,
        policy: str = POLICY_CONFIRMED,
        delivery_no: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        service_nos = [str(item).strip() for item in service_nos if str(item).strip()]
        if not service_nos:
            return None, "至少选择一个数据服务才能发起批量交付"
        if policy not in POLICIES:
            return None, f"截面策略「{policy}」不支持，可选：{'、'.join(POLICIES)}"
        params = {
            str(key).strip(): str(val).strip()
            for key, val in (params or {}).items()
            if str(val).strip()
        }

        services: list[dict[str, Any]] = []
        for service_no in service_nos:
            service = self._service_by_no(service_no)
            if service is None:
                return None, f"数据服务「{service_no}」不存在或已归档"
            services.append(service)

        # 先整体确认截面：任一服务缺截面就挂起，不生成半包。
        selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
        gaps: list[dict[str, Any]] = []
        for service in services:
            dataset = str(service.get("输出数据集") or "")
            if dataset not in SOURCE_MODULES:
                gaps.append({
                    "服务编号": service.get("服务编号"),
                    "输出数据集": dataset,
                    "原因": f"输出数据集「{dataset}」没有可读取的明细来源",
                })
                continue
            snapshot, reason = self._pick_snapshot(dataset, policy)
            if snapshot is None:
                gaps.append({
                    "服务编号": service.get("服务编号"),
                    "输出数据集": dataset,
                    "原因": reason,
                })
                continue
            selected.append((service, snapshot))

        seq = max(
            (int(row.get("id", 0)) for row in store.rows(DELIVERY_MODULE)), default=0
        ) + 1
        if delivery_no:
            existing = self.get_delivery(delivery_no)
            if existing is not None:
                seq = int(existing.get("id", seq))
        else:
            delivery_no = f"DLV-{datetime.now():%Y%m%d}-{seq:04d}"
        base: dict[str, Any] = {
            "id": seq,
            "交付编号": delivery_no,
            "服务编号": [service.get("服务编号") for service in services],
            "服务名称": [service.get("服务名称") for service in services],
            "查询参数": params,
            "截面策略": policy,
            "口径说明": POLICY_NOTES[policy],
            "交付时间": _now(),
        }
        if gaps:
            suspended = {
                **base,
                "状态": "待补取",
                "缺口": gaps,
                "服务范围": [],
                "订单合计": 0.0,
                "退款合计": 0.0,
                "明细条数": 0,
                "核对": None,
            }
            message = (
                f"交付 {delivery_no} 已挂起补取："
                + "；".join(f"{gap['输出数据集']}（{gap['原因']}）" for gap in gaps)
            )
            if existing := self.get_delivery(delivery_no):
                existing.clear()
                existing.update(suspended)
                return existing, message
            store.rows(DELIVERY_MODULE).append(suspended)
            return suspended, message

        snap_rows = store.rows(SNAPSHOT_MODULE)
        lines: list[dict[str, Any]] = []
        scope: list[dict[str, Any]] = []
        for service, snapshot in selected:
            dataset = str(snapshot.get("数据集"))
            rows, boundary = self._query_snapshot(snapshot, params)
            subtotal = 0
            for index, source_row in enumerate(rows, start=1):
                amount = _as_amount(source_row.get(AMOUNT_FIELD[dataset]))
                subtotal += amount or 0
                line = {
                    "id": len(snap_rows) + 1,
                    "交付编号": delivery_no,
                    "服务编号": service.get("服务编号"),
                    "服务名称": service.get("服务名称"),
                    "输出数据集": dataset,
                    "序号": index,
                    "记账金额": amount,
                    "取数边界": boundary,
                    "明细": dict(source_row),
                }
                snap_rows.append(line)
                lines.append(line)
            scope.append({
                "服务编号": service.get("服务编号"),
                "服务名称": service.get("服务名称"),
                "输出数据集": dataset,
                "截面号": snapshot.get("截面号"),
                "截面版本": snapshot.get("版本"),
                "截面状态": snapshot.get("状态"),
                "取数边界": boundary,
                "记账合计": _fmt_amount(subtotal),
                "记录条数": len(rows),
            })

        summary = self._summarize(lines)
        pending_notes = self._pending_notes(selected, policy)
        delivery = {
            **base,
            "状态": "已交付",
            "服务范围": scope,
            "订单合计": _yuan(sum(int(line.get("记账金额") or 0) for line in self._unique(lines, "订单"))),
            "退款合计": _yuan(sum(int(line.get("记账金额") or 0) for line in self._unique(lines, "退款"))),
            "明细条数": len(lines),
            "待复核": pending_notes,
            "核对": summary["核对"],
        }
        if existing_delivery := self.get_delivery(delivery_no):
            existing_delivery.clear()
            existing_delivery.update(delivery)
        else:
            store.rows(DELIVERY_MODULE).append(delivery)
        message = f"批量交付 {delivery_no} 已生成，共 {len(lines)} 条明细"
        if pending_notes:
            message += "；存在待确认更正，交付采用已确认截面，可发起最新重取复核"
        return delivery, message

    def _pending_notes(
        self, selected: list[tuple[dict[str, Any], dict[str, Any]]], policy: str
    ) -> list[dict[str, Any]]:
        notes: list[dict[str, Any]] = []
        for service, snapshot in selected:
            dataset = str(snapshot.get("数据集"))
            latest = self._snapshots_of(dataset)[-1] if self._snapshots_of(dataset) else snapshot
            if int(latest.get("版本", 0)) > int(snapshot.get("版本", 0)):
                notes.append({
                    "服务编号": service.get("服务编号"),
                    "输出数据集": dataset,
                    "采用截面": snapshot.get("截面号"),
                    "更新截面": latest.get("截面号"),
                    "更新截面状态": latest.get("状态"),
                    "说明": (
                        f"本交付采用{POLICY_NOTES[policy]}；"
                        f"源数据另有更新截面 {latest.get('截面号')}（{latest.get('状态', '')}），未混入本交付"
                    ),
                })
        return notes

    def _unique(self, lines: list[dict[str, Any]], dataset: str) -> list[dict[str, Any]]:
        """同一订单/退款单在交付里只记一次，避免关联展开造成重复累计。"""
        key_field = DOC_KEY[dataset]
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for line in lines:
            if line.get("输出数据集") != dataset:
                continue
            key = str(line["明细"].get(key_field) or "")
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(line)
        return unique

    def _summarize(self, lines: list[dict[str, Any]]) -> dict[str, Any]:
        """按订单记实付、按退款单记退款，并把退款关联回原订单。"""
        orders = self._unique(lines, "订单")
        refunds = self._unique(lines, "退款")
        order_by_no = {
            str(line["明细"].get("订单号")): line
            for line in orders
            if line["明细"].get("订单号")
        }
        matched: dict[str, list[dict[str, Any]]] = {}
        orphans: list[dict[str, Any]] = []
        for line in refunds:
            order_no = str(line["明细"].get("原订单号") or "")
            if order_no and order_no in order_by_no:
                matched.setdefault(order_no, []).append(line)
            else:
                orphans.append(line)

        order_total = sum(int(line.get("记账金额") or 0) for line in orders)
        refund_total = sum(int(line.get("记账金额") or 0) for line in refunds)
        details: list[dict[str, Any]] = []
        for order_no, order_line in order_by_no.items():
            linked = matched.get(order_no, [])
            refunded = sum(int(item.get("记账金额") or 0) for item in linked)
            net = int(order_line.get("记账金额") or 0) - refunded
            details.append({
                "订单号": order_no,
                "实付金额": _fmt_amount(order_line.get("记账金额")),
                "关联退款单号": [item["明细"].get("退款单号") for item in linked],
                "关联退款": [_fmt_amount(item.get("记账金额")) for item in linked],
                "净额": _fmt_amount(net),
            })
        return {
            "口径": {
                "实付金额": "按订单记账，一笔订单只累计一次实付",
                "退款金额": "按退款单记账，同一订单多张退款单逐笔累计",
                "孤立退款": "找不到原订单的退款仍计入退款合计，单独列出",
                "截面": "一次交付只采用一种截面策略，不与另一种口径混用",
            },
            "核对": {
                "订单合计": _fmt_amount(order_total),
                "退款合计": _fmt_amount(refund_total),
                "订单笔数": len(orders),
                "退款笔数": len(refunds),
                "订单明细": details,
                "孤立退款": [
                    {
                        "退款单号": item["明细"].get("退款单号"),
                        "退款金额": _fmt_amount(item.get("记账金额")),
                        "原订单号": item["明细"].get("原订单号"),
                    }
                    for item in orphans
                ],
            },
        }

    def get_delivery_detail(self, delivery_no: str) -> dict[str, Any] | None:
        """按交付编号回放当时落下的明细与金额，不重新访问源数据。"""
        delivery = self.get_delivery(delivery_no)
        if delivery is None:
            return None
        lines = self.delivery_lines(delivery_no)
        summary = self._summarize(lines)
        detail = dict(delivery)
        detail["明细"] = lines
        detail["核对"] = summary["核对"] if lines else None
        detail["口径"] = summary["口径"]
        return detail

    def retry_delivery(self, delivery_no: str) -> tuple[dict[str, Any] | None, str]:
        """对挂起交付按原策略重新取截面；仍不足则保持挂起。"""
        delivery = self.get_delivery(delivery_no)
        if delivery is None:
            return None, f"交付 {delivery_no} 不存在"
        if delivery.get("状态") != "待补取":
            return delivery, f"交付 {delivery_no} 已是{delivery.get('状态')}，无需补取"
        created, message = self.create_delivery(
            list(delivery.get("服务编号") or []),
            dict(delivery.get("查询参数") or {}),
            str(delivery.get("截面策略") or POLICY_CONFIRMED),
            delivery_no=delivery_no,
        )
        if created is None:
            return None, message
        if created.get("状态") == "已交付":
            return created, f"交付 {delivery_no} 已补齐截面并完成交付"
        return created, message

    def reconcile(self, delivery_no: str) -> dict[str, Any] | None:
        """复核交付：留存明细 vs 当前源数据 / 最新截面，逐条标出差异。"""
        delivery = self.get_delivery(delivery_no)
        if delivery is None:
            return None
        lines = self.delivery_lines(delivery_no)
        summary = self._summarize(lines)
        changed: list[dict[str, Any]] = []
        for line in lines:
            dataset = str(line.get("输出数据集") or "")
            module = SOURCE_MODULES.get(dataset)
            if module is None:
                continue
            key_field = DOC_KEY[dataset]
            key = line["明细"].get(key_field)
            current = next(
                (row for row in store.rows(module) if row.get(key_field) == key), None
            )
            if current is None:
                changed.append({
                    "输出数据集": dataset,
                    "单据号": key,
                    "变化": "当前源数据已不存在",
                })
            elif dict(current) != line["明细"]:
                changed.append({
                    "输出数据集": dataset,
                    "单据号": key,
                    "变化": "当前源数据已更正",
                    "交付时": line["明细"],
                    "当前": dict(current),
                    "交付时金额": _fmt_amount(line.get("记账金额")),
                    "当前金额": _fmt_amount(
                        _as_amount(dict(current).get(AMOUNT_FIELD[dataset]))
                    ),
                })
        latest = {
            dataset: (self._snapshots_of(dataset)[-1].get("截面号") if self._snapshots_of(dataset) else None)
            for dataset in {line.get("输出数据集") for line in lines}
        }
        return {
            "交付编号": delivery_no,
            "交付时间": delivery.get("交付时间"),
            "状态": delivery.get("状态"),
            "截面策略": delivery.get("截面策略"),
            "服务范围": delivery.get("服务范围", []),
            "口径": summary["口径"],
            "留存核对": summary["核对"],
            "差异": changed,
            "差异条数": len(changed),
            "最新截面": latest,
        }

    # ------------------------------------------------------------------
    # 源数据更正（验收用）：更正后生成新的待确认截面，不覆盖已确认截面
    # ------------------------------------------------------------------
    def correct_source(
        self, dataset: str, doc_no: str, field: str, value: Any
    ) -> tuple[dict[str, Any] | None, str]:
        module = SOURCE_MODULES.get(dataset)
        if module is None:
            return None, f"输出数据集「{dataset}」不支持源数据更正"
        expected = AMOUNT_FIELD[dataset]
        if field != expected:
            return None, f"数据集「{dataset}」只支持更正的金额字段为「{expected}」"
        amount = _as_amount(value)
        if amount is None or amount < 0:
            return None, f"更正金额「{value}」不是有效金额"
        key_field = DOC_KEY[dataset]
        target = next(
            (row for row in store.rows(module) if row.get(key_field) == doc_no), None
        )
        if target is None:
            return None, f"{dataset}单据「{doc_no}」在源数据中不存在"
        before = target.get(expected)
        target[expected] = _fmt_amount(amount)

        snaps = self._snapshots_of(dataset)
        version = max((int(row.get("版本", 0)) for row in snaps), default=0) + 1
        prefix = DATASET_PREFIX.get(dataset, dataset[:3].upper())
        snapshot = {
            "id": max(
                (int(row.get("id", 0)) for row in store.rows(SNAPSHOT_SOURCE_MODULE)),
                default=0,
            ) + 1,
            "数据集": dataset,
            "截面号": f"{prefix}-V{version}",
            "版本": version,
            "状态": "待确认",
            "生成时间": _now(),
            "说明": f"源数据更正 {doc_no}（{before} → {target[expected]}）后生成，待服务确认",
            "明细": [dict(row) for row in store.rows(module)],
        }
        store.rows(SNAPSHOT_SOURCE_MODULE).append(snapshot)
        return snapshot, (
            f"{dataset}单据 {doc_no} 已由 {before} 更正为 {target[expected]}，"
            f"生成待确认截面 {snapshot['截面号']}"
        )
