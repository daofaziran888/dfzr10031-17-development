"""数据导出按交付编号交付：记录、关联依据与留存复查。"""
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


class ExportDeliveryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        reset_store()
        self.client = TestClient(app)
        response = self.client.post(
            "/api/data_service/deliveries",
            json={"values": {"服务编号": ["SVC-ORDER", "SVC-REFUND"]}},
        )
        self.delivery_no = response.json()["entry"]["交付编号"]

    def file(self) -> dict:
        payload = self.client.post(
            "/api/export/packages", json={"values": {"交付编号": self.delivery_no}}
        ).json()
        self.assertTrue(payload["ok"], payload["message"])
        return payload["entry"]

    def test_package_delivers_records_with_basis(self) -> None:
        package = self.file()
        self.assertEqual(package["记录条数"], 4)
        self.assertEqual(package["订单合计"], 120.0)
        self.assertEqual(package["退款合计"], 57.0)
        by_no = {record["单据号"]: record for record in package["记录"]}
        order = by_no["ORD-1001"]
        self.assertEqual(order["记录类型"], "订单")
        self.assertEqual(order["记账金额文本"], "120.00")
        self.assertEqual(
            [basis["退款单号"] for basis in order["关联依据"]], ["REF-1001", "REF-1002"]
        )
        orphan = by_no["REF-9001"]
        self.assertEqual(orphan["关联依据"][0]["关联状态"], "孤立退款，未找到原订单")
        self.assertEqual(by_no["REF-1001"]["关联依据"][0]["关联状态"], "已关联原订单")
        for record in package["记录"]:
            self.assertIn("取数边界", record)
            self.assertIn("截面号", record["取数边界"])

    def test_package_replays_after_source_correction(self) -> None:
        self.file()
        self.client.post(
            "/api/data_service/source/退款/corrections",
            json={"values": {"单据号": "REF-1002", "字段": "退款金额", "金额": 25}},
        )
        package = self.client.get(f"/api/export/packages/{self.delivery_no}").json()
        self.assertEqual(package["退款合计"], 57.0)
        line = next(item for item in package["记录"] if item["单据号"] == "REF-1002")
        self.assertEqual(line["记录"]["退款金额"], "20.00")

    def test_suspended_delivery_cannot_be_exported(self) -> None:
        payload = self.client.post(
            "/api/data_service/deliveries",
            json={"values": {"服务编号": ["SVC-ORDER", "SVC-CHANNEL"]}},
        ).json()
        suspended_no = payload["entry"]["交付编号"]
        result = self.client.post(
            "/api/export/packages", json={"values": {"交付编号": suspended_no}}
        ).json()
        self.assertFalse(result["ok"])
        self.assertIn("待补取", result["message"])


if __name__ == "__main__":
    unittest.main()
