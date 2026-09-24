import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException

from routers.data_sources import get_data_source_details


class FakeResult:
    def __init__(self, rows=None, scalars=None):
        self.rows = rows or []
        self.scalar_rows = scalars or []

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return FakeResult(rows=self.scalar_rows)


class DataSourceDetailsTests(unittest.TestCase):
    def test_missing_source_returns_404(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=FakeResult()))

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(get_data_source_details(404, db))

        self.assertEqual(raised.exception.status_code, 404)

    def test_nests_classification_analysis_assets_and_signals(self):
        db = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    FakeResult(rows=[{"src_id": 7, "src_title": "Market news"}]),
                    FakeResult(rows=[{"cls_id": 11, "cls_category": "markets"}]),
                    FakeResult(
                        rows=[
                            {
                                "cla_cls_id": 11,
                                "ast_id": 5,
                                "ast_symbol": "NVDA",
                            }
                        ]
                    ),
                    FakeResult(
                        rows=[
                            {
                                "cln_cls_id": 11,
                                "nic_id": 3,
                                "nic_name": "AI",
                            }
                        ]
                    ),
                    FakeResult(scalars=[21]),
                    FakeResult(
                        rows=[
                            {
                                "anl_id": 21,
                                "anl_cls_id": 11,
                                "anl_response_text": "Full analysis text",
                            }
                        ]
                    ),
                    FakeResult(
                        rows=[
                            {
                                "aas_anl_id": 21,
                                "aas_ast_id": 5,
                                "asset_symbol": "NVDA",
                            }
                        ]
                    ),
                    FakeResult(
                        rows=[
                            {
                                "sig_id": 31,
                                "sig_anl_id": 21,
                                "asset_symbol": "NVDA",
                                "sig_action": "hold",
                            }
                        ]
                    ),
                    FakeResult(
                        rows=[
                            {
                                "ans_anl_id": 21,
                                "src_id": 7,
                                "src_title": "Market news",
                            }
                        ]
                    ),
                    FakeResult(
                        rows=[SimpleNamespace(inp_anl_id=21, inp_src_anl_id=9)]
                    ),
                ]
            )
        )

        result = asyncio.run(get_data_source_details(7, db))

        self.assertEqual(
            result["overview"],
            {
                "classification_count": 1,
                "analysis_count": 1,
                "signal_count": 1,
                "detected_asset_count": 1,
            },
        )
        self.assertEqual(result["classifications"][0]["assets"][0]["ast_symbol"], "NVDA")
        self.assertEqual(result["classifications"][0]["niches"][0]["nic_name"], "AI")
        analysis = result["analyses"][0]
        self.assertEqual(
            analysis["relationships"],
            ["classification_result", "supporting_source"],
        )
        self.assertEqual(analysis["signals"][0]["sig_action"], "hold")
        self.assertTrue(analysis["supporting_sources"][0]["is_requested_source"])
        self.assertEqual(analysis["input_analysis_ids"], [9])


if __name__ == "__main__":
    unittest.main()
