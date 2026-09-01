from __future__ import annotations

import argparse
import os
import unittest
from unittest import mock

from runtime.adapters.database import _load_hotel_enabled_ota_channels
from runtime.adapters.database import _first_metric_value, _peer_rank_from_rows


def _args(hotel_id: str = "puyue") -> argparse.Namespace:
    return argparse.Namespace(hotel_id=hotel_id)


class TestOtaChannelEnvOverride(unittest.TestCase):
    @mock.patch.dict(os.environ, {"HOTEL_OTA_ENABLED_CHANNELS": "meituan"}, clear=False)
    def test_enabled_channels_env_whitelist(self) -> None:
        # #1:HOTEL_OTA_ENABLED_CHANNELS 应被读取,直接决定启用渠道(conn 都不需要碰)。
        channels, warnings = _load_hotel_enabled_ota_channels(None, _args(), {})
        self.assertEqual(channels, {"meituan"})
        self.assertEqual(warnings, [])

    @mock.patch.dict(os.environ, {"HOTEL_OTA_DISABLED_CHANNELS": "ctrip"}, clear=False)
    def test_disabled_channels_env_blacklist(self) -> None:
        # 关闭携程 → 启用集为已知渠道去掉携程 = {meituan}。
        channels, _ = _load_hotel_enabled_ota_channels(None, _args(), {})
        self.assertEqual(channels, {"meituan"})


class TestS14MerchantOperationScoreExtraction(unittest.TestCase):
    def test_merchant_operation_score_metric_name_matches(self) -> None:
        # A:商家运营分之前根本没抽,补的 token 应能命中行式指标"商家运营分"。
        rows = [
            {"metric_name": "曝光人数", "metric_value": 1085},
            {"metric_name": "商家运营分", "metric_value": 88},
        ]
        self.assertEqual(_first_metric_value(rows, "商家运营", "operation_score", "运营分"), 88.0)

    def test_peer_rank_parses_rank_over_total_string(self) -> None:
        # A:competitor_rank 生产是 "3/21" 字符串,应解析出排名 3(而非当数字失败→缺失)。
        rows = [{"competitor_rank": None}, {"competitor_rank": "3/21"}]
        self.assertEqual(_peer_rank_from_rows(rows, "competitor_rank"), 3.0)


if __name__ == "__main__":
    unittest.main()
