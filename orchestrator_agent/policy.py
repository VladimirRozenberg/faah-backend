"""Non-AI safety rules defining the orchestrator's authority."""

from dataclasses import dataclass

from orchestrator_agent.schemas import ActionType, DecisionProposal, Instruction


class PolicyRejected(ValueError):
    pass


@dataclass(frozen=True)
class OrchestratorPolicy:
    allowed_feeds: frozenset[str]
    min_rss_interval_seconds: int = 300
    max_rss_interval_seconds: int = 7_200
    minimum_confidence: float = 0.60

    def authorize(self, proposal: DecisionProposal) -> Instruction:
        if proposal.target not in self.allowed_feeds:
            raise PolicyRejected(f"Unknown or forbidden RSS feed: {proposal.target}")

        if proposal.confidence < self.minimum_confidence:
            raise PolicyRejected(
                f"Confidence must be at least {self.minimum_confidence:.2f}"
            )

        parameters = dict(proposal.parameters)
        if proposal.action is ActionType.SET_RSS_INTERVAL:
            interval = parameters.get("seconds")
            if isinstance(interval, bool) or not isinstance(interval, int):
                raise PolicyRejected("seconds must be an integer")
            if not self.min_rss_interval_seconds <= interval <= self.max_rss_interval_seconds:
                raise PolicyRejected(
                    "RSS interval must be between "
                    f"{self.min_rss_interval_seconds} and "
                    f"{self.max_rss_interval_seconds} seconds"
                )
            parameters = {"seconds": interval}
        elif parameters:
            raise PolicyRejected(f"{proposal.action.value} accepts no parameters")

        return Instruction(
            action=proposal.action,
            target=proposal.target,
            parameters=parameters,
            reason=proposal.reason,
            confidence=proposal.confidence,
        )
