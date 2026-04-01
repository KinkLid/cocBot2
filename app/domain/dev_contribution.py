from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ContributionInput:
    stars: int
    attacker_position: int
    attacker_town_hall: int
    defender_town_hall: int
    defender_position: int
    destruction: float


@dataclass(slots=True)
class ContributionResult:
    score: float
    explanation: str


class DevContributionFormula:
    """Небоевая dev-формула вклада, изолированная от основной статистики."""

    def calculate(self, data: ContributionInput) -> ContributionResult:
        star_component = data.stars * 10.0
        destruction_component = data.destruction / 10.0
        position_delta = data.attacker_position - data.defender_position
        position_component = max(position_delta, 0) * 0.7 + max(-position_delta, 0) * 0.25
        th_delta = data.defender_town_hall - data.attacker_town_hall
        th_component = th_delta * 2.0
        triple_bonus = 8.0 if data.stars == 3 else 0.0

        score = round(star_component + destruction_component + position_component + th_component + triple_bonus, 2)
        explanation = (
            f"stars={star_component:.2f}; destruction={destruction_component:.2f}; "
            f"position={position_component:.2f}; th_delta={th_component:.2f}; triple={triple_bonus:.2f}"
        )
        return ContributionResult(score=score, explanation=explanation)
