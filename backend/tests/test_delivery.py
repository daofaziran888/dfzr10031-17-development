"""批量交付与财务对账验收：订单/退款明细、口径、留存与复核。"""
from __future__ import annotations

import copy
import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.seed import SEED_ROWS
from app.store import store


def reset_store() -> None:
    for name, rows in SEED_ROWS.items():
        table = store.rows(name)
        table.clear()
        table.extend(copy.deepcopy(rows))


class DeliveryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        reset_store()
        self.client = TestClient(app)

    def deliver(self, services: list[str], policy: str | None = None, params: dict | None = None) -> dict:
        values: dict = {"服务编号": services}
        if policy:
            values["截面策略"] = policy
        if params:
            values["查询参数"] = params
        response = self.client.post("/api/data_service/deliveries", json={"values": values})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_order_total_refund_total_and_orphan(self) -> None:
        payload = self.deliver(["SVC-ORDER", "SVC-REFUND"])
        self.assertTrue(payload["ok"], payload["message"])
        delivery = payload["entry"]
        self.assertEqual(delivery["状态"], "已交付")
        self.assertEqual(delivery["订单合计"], 120.0)
        self.assertEqual(delivery["退款合计"], 57.0)
        self.assertEqual(delivery["核对"]["订单合计"], "120.00")
        self.assertEqual(delivery["核对"]["退款合计"], "57.00")
        # 同一订单两张退款单：实付只累计一次，退款逐笔累计。
        detail = delivery["核对"]["订单明细"][0]
        self.assertEqual(detail["订单号"], "ORD-1001")
        self.assertEqual(detail["实付金额"], "120.00")
        self.assertEqual(detail["关联退款"], ["30.00", "20.00"])
        self.assertEqual(detail["净额"], "70.00")
        self.assertEqual([item["退款单号"] for item in delivery["核对"]["孤立退款"]], ["REF-9001"])
        self.assertEqual(delivery["核对"]["孤立退款"][0]["退款金额"], "7.00")

    def test_replay_uses_saved_lines_after_source_correction(self) -> None:
        delivery_no = self.deliver(["SVC-ORDER", "SVC-REFUND"])["entry"]["交付编号"]
        correction = self.client.post(
            "/api/data_service/source/退款/corrections",
            json={"values": {"单据号": "REF-1002", "字段": "退款金额", "金额": 25}},
        )
        self.assertTrue(correction.json()["ok"], correction.text)

        replay = self.client.get(f"/api/data_service/deliveries/{delivery_no}").json()
        self.assertEqual(replay["退款合计"], 57.0)
        self.assertEqual(len(replay["明细"]), 4)
        amounts = {
            line["明细"]["退款单号"]: line["明细"]["退款金额"]
            for line in replay["明细"]
            if line["输出数据集"] == "退款"
        }
        self.assertEqual(amounts["REF-1002"], "20.00")

        reconcile = self.client.get(
            f"/api/data_service/deliveries/{delivery_no}/reconcile"
        ).json()
        self.assertEqual(reconcile["差异条数"], 1)
        diff = reconcile["差异"][0]
        self.assertEqual(diff["单据号"], "REF-1002")
        self.assertEqual(diff["交付时金额"], "20.00")
        self.assertEqual(diff["当前金额"], "25.00")
        # 留存明细本身不因源数据更正而变化。
        self.assertEqual(reconcile["留存核对"]["退款合计"], "57.00")

    def test_two_policies_are_isolated(self) -> None:
        confirmed = self.deliver(["SVC-ORDER", "SVC-REFUND"], "已确认一致")["entry"]
        self.client.post(
            "/api/data_service/source/退款/corrections",
            json={"values": {"单据号": "REF-1002", "字段": "退款金额", "金额": 25}},
        )
        still_confirmed = self.deliver(["SVC-ORDER", "SVC-REFUND"], "已确认一致")["entry"]
        latest = self.deliver(["SVC-ORDER", "SVC-REFUND"], "最新重取")["entry"]

        self.assertEqual(confirmed["退款合计"], 57.0)
        self.assertEqual(still_confirmed["退款合计"], 57.0)
        self.assertEqual(latest["退款合计"], 62.0)
        self.assertEqual({item["截面状态"] for item in still_confirmed["服务范围"]}, {"已确认"})
        self.assertEqual(
            {item["截面号"] for item in latest["服务范围"]}, {"ORD-V1", "REF-V2"}
        )
        # 每个交付只采用一种策略，且记录在案。
        self.assertEqual(still_confirmed["截面策略"], "已确认一致")
        self.assertEqual(latest["截面策略"], "最新重取")

    def test_confirmed_policy_flags_pending_correction(self) -> None:
        self.client.post(
            "/api/data_service/source/退款/corrections",
            json={"values": {"单据号": "REF-1002", "字段": "退款金额", "金额": 25}},
        )
        delivery = self.deliver(["SVC-ORDER", "SVC-REFUND"], "已确认一致")["entry"]
        self.assertEqual(delivery["退款合计"], 57.0)
        self.assertEqual(len(delivery["待复核"]), 1)
        note = delivery["待复核"][0]
        self.assertEqual(note["采用截面"], "REF-V1")
        self.assertEqual(note["更新截面"], "REF-V2")

    def test_confirm_latest_then_confirmed_policy_uses_it(self) -> None:
        self.client.post(
            "/api/data_service/source/退款/corrections",
            json={"values": {"单据号": "REF-1002", "字段": "退款金额", "金额": 25}},
        )
        confirmed = self.client.post(
            "/api/data_service/snapshots/REF-V2/confirm"
        ).json()
        self.assertTrue(confirmed["ok"], confirmed["message"])
        delivery = self.deliver(["SVC-ORDER", "SVC-REFUND"], "已确认一致")["entry"]
        self.assertEqual(delivery["退款合计"], 62.0)
        self.assertEqual(
            {item["截面号"] for item in delivery["服务范围"]}, {"ORD-V1", "REF-V2"}
        )
        self.assertEqual(delivery["待复核"], [])

    def test_missing_snapshot_suspends_without_partial_lines(self) -> None:
        payload = self.deliver(["SVC-ORDER", "SVC-CHANNEL"])
        self.assertFalse(payload["ok"])
        delivery = payload["entry"]
        self.assertEqual(delivery["状态"], "待补取")
        self.assertEqual(delivery["明细条数"], 0)
        detail = self.client.get(f"/api/data_service/deliveries/{delivery['交付编号']}").json()
        self.assertEqual(detail["明细"], [])
        self.assertEqual(len(detail["缺口"]), 1)

        retried = self.client.post(
            f"/api/data_service/deliveries/{delivery['交付编号']}/retry"
        ).json()
        self.assertFalse(retried["ok"])
        self.assertEqual(retried["entry"]["状态"], "待补取")

    def test_query_boundary_is_recorded_and_apply(self) -> None:
        delivery = self.deliver(
            ["SVC-REFUND"],
            params={"原订单号": "ORD-1001", "开始日期": "2026-11-06"},
        )["entry"]
        self.assertEqual(delivery["明细条数"], 1)
        self.assertEqual(delivery["退款合计"], 20.0)
        boundary = delivery["服务范围"][0]["取数边界"]
        self.assertEqual(boundary["截面号"], "REF-V1")
        self.assertEqual(boundary["查询参数"]["原订单号"], "ORD-1001")
        self.assertEqual(boundary["查询参数"]["开始日期"], "2026-11-06")
        self.assertEqual(boundary["命中行数"], 1)

    def test_same_delivery_number_replays_same_lines(self) -> None:
        delivery = self.deliver(["SVC-ORDER", "SVC-REFUND"])["entry"]
        first = self.client.get(f"/api/data_service/deliveries/{delivery['交付编号']}").json()
        second = self.client.get(f"/api/data_service/deliveries/{delivery['交付编号']}").json()
        self.assertEqual(first["明细"], second["明细"])
        self.assertEqual(first["订单合计"], second["订单合计"])
        self.assertEqual(first["退款合计"], second["退款合计"])

    def test_each_service_scope_can_be_reviewed(self) -> None:
        delivery = self.deliver(["SVC-ORDER", "SVC-REFUND"])["entry"]
        scope = {item["输出数据集"]: item for item in delivery["服务范围"]}
        self.assertEqual(scope["订单"]["截面号"], "ORD-V1")
        self.assertEqual(scope["订单"]["记账合计"], "120.00")
        self.assertEqual(scope["订单"]["记录条数"], 1)
        self.assertEqual(scope["退款"]["截面号"], "REF-V1")
        self.assertEqual(scope["退款"]["记账合计"], "57.00")
        self.assertEqual(scope["退款"]["记录条数"], 3)
        for item in scope.values():
            self.assertEqual(item["取数边界"]["命中行数"], item["记录条数"])


if __name__ == "__main__":
    unittest.main()
