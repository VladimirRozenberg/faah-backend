import unittest
from datetime import datetime, timedelta, timezone

from live_market.market_schemas import LiveQuote
from portfolio_strategist.brain import validate_strategist_coverage
from portfolio_strategist.brain import parse_strategist_decision
from portfolio_strategist.detector import detect_price_movement, risk_is_compatible
from portfolio_strategist.schemas import (
    StrategistContext,
    StrategistPosition,
    StrategistReviewDecision,
    StrategistSignal,
    HoldingAssessment,
)
from prompt.response_models import FinancialAnalysisResult


class OpportunityDetectorTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)

    def quote(self, price: float, at: datetime | None = None) -> LiveQuote:
        return LiveQuote(symbol="GC=F", price=price, timestamp=at or self.now)

    def test_detects_two_percent_drop_with_precise_reason_data(self):
        movement = detect_price_movement(
            self.quote(100, self.now),
            self.quote(97.9, self.now + timedelta(minutes=1)),
        )

        self.assertIsNotNone(movement)
        self.assertEqual(movement.event_type, "price_drop")
        self.assertAlmostEqual(movement.change_pct, -2.1)
        self.assertEqual(movement.window_seconds, 60)

    def test_ignores_noise_old_windows_and_replayed_quotes(self):
        self.assertIsNone(
            detect_price_movement(
                self.quote(100, self.now),
                self.quote(101, self.now + timedelta(minutes=1)),
            )
        )
        self.assertIsNone(
            detect_price_movement(
                self.quote(100, self.now),
                self.quote(103, self.now + timedelta(hours=1)),
            )
        )
        self.assertIsNone(
            detect_price_movement(
                self.quote(100, self.now),
                self.quote(103, self.now),
            )
        )

    def test_risk_compatibility_is_conservative(self):
        self.assertTrue(risk_is_compatible("medium", "low"))
        self.assertTrue(risk_is_compatible("medium", "medium"))
        self.assertFalse(risk_is_compatible("medium", "high"))
        self.assertFalse(risk_is_compatible(None, None))

    def test_analysis_missing_labels_gets_conservative_defaults(self):
        result = FinancialAnalysisResult.model_validate(
            {
                "anl_response_text": "Useful researched answer.",
                "anl_summary": "Summary.",
                "anl_direction": "mixed",
                "anl_market_sentiment": "mixed",
                "anl_confidence": 70,
            }
        )
        self.assertEqual(result.anl_risk_level, "high")
        self.assertEqual(result.anl_timeframe, "multiple")


class StrategistCoverageTests(unittest.TestCase):
    def context(self, review_type="full") -> StrategistContext:
        return StrategistContext(
            review_type=review_type,
            reason="Scheduled review",
            portfolio={"portfolio_id": 1},
            positions=[
                StrategistPosition(
                    asset_id=3,
                    symbol="GC=F",
                    name="Gold",
                    asset_type="future",
                    quantity=1,
                    average_purchase_price=2_500,
                )
            ],
        )

    def decision(self, assessments=None, opportunities=None, **updates):
        return StrategistReviewDecision(
            summary="The portfolio remains stable.",
            portfolio_health="stable",
            holding_assessments=assessments or [],
            opportunities=opportunities or [],
            next_review_notes="Recheck at the next scheduled review.",
            **updates,
        )

    def test_full_review_must_cover_every_holding(self):
        with self.assertRaisesRegex(ValueError, "omitted holdings"):
            validate_strategist_coverage(self.context(), self.decision())

        validate_strategist_coverage(
            self.context(),
            self.decision(
                assessments=[
                    HoldingAssessment(
                        asset_symbol="GC=F",
                        verdict="watch",
                        reason="Recent movement remains unexplained.",
                    )
                ]
            ),
        )

    def test_targeted_unowned_signal_must_have_explicit_conclusion(self):
        context = self.context("targeted_signal")
        context.triggering_signal = StrategistSignal(
            signal_id=9,
            analysis_id=12,
            asset_id=4,
            asset_symbol="AAPL",
            action="buy",
            created_at=datetime.now(timezone.utc),
        )
        with self.assertRaisesRegex(ValueError, "explicit conclusion"):
            validate_strategist_coverage(context, self.decision())

        validate_strategist_coverage(
            context,
            self.decision(
                targeted_conclusion="no_action",
                targeted_reason="The signal does not materially fit the portfolio.",
            ),
        )

    def test_strategist_cannot_invent_an_opportunity_asset(self):
        from portfolio_strategist.schemas import StrategistOpportunity

        with self.assertRaisesRegex(ValueError, "assets it was not supplied"):
            validate_strategist_coverage(
                self.context(),
                self.decision(
                    assessments=[
                        HoldingAssessment(
                            asset_symbol="GC=F",
                            verdict="unchanged",
                            reason="No material change.",
                        )
                    ],
                    opportunities=[
                        StrategistOpportunity(
                            asset_symbol="INVENTED",
                            reason="Unsupported idea.",
                            confidence=90,
                        )
                    ],
                ),
            )

    def test_model_response_may_omit_optional_next_review_note(self):
        decision = parse_strategist_decision(
            '{"summary":"Stable.","portfolio_health":"stable"}'
        )
        self.assertIn("next scheduled", decision.next_review_notes)


if __name__ == "__main__":
    unittest.main()
