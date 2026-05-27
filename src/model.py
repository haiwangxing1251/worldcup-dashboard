"""
Core Prediction Model: ELO Rating → Poisson Distribution

Converts ELO ratings to match outcome probabilities using:
1. ELO difference → expected goal difference
2. Expected goals → Poisson distribution for score simulation
3. Draw probability from score equality
"""

import math
import random
from typing import Tuple


class EloPoissonModel:
    """
    Football match prediction model based on ELO ratings and Poisson distribution.

    Calibration:
    - Average World Cup goals per game: ~2.6
    - 200 ELO points ≈ 1 goal advantage (empirical calibration)
    - Poisson λ constrained to [0.3, 3.5] to prevent unrealistic scores
    """

    AVG_TOTAL_GOALS = 2.6   # Average total goals per match in recent World Cups
    ELO_PER_GOAL = 200.0    # ELO point difference corresponding to 1 goal advantage
    HOME_ADVANTAGE = 30.0   # ELO points for home/neutral advantage (minor for neutral venues)
    MIN_LAMBDA = 0.3
    MAX_LAMBDA = 4.0
    RANDOM_SEED = 42

    def __init__(self, seed: int = None):
        if seed is not None:
            random.seed(seed)

    @staticmethod
    def win_probability(elo_a: float, elo_b: float) -> float:
        """
        Calculate the probability of team A winning based on ELO difference.
        Uses the standard ELO formula: P = 1 / (1 + 10^(-dr/400))
        """
        dr = elo_a - elo_b
        return 1.0 / (1.0 + math.pow(10, -dr / 400.0))

    def expected_goals(self, elo_a: float, elo_b: float) -> Tuple[float, float]:
        """
        Calculate expected goals (λ) for both teams based on ELO ratings.

        Args:
            elo_a: ELO rating of team A
            elo_b: ELO rating of team B

        Returns:
            Tuple of (lambda_a, lambda_b) - expected goals for each team
        """
        dr = elo_a - elo_b

        # Expected goal difference from ELO difference
        expected_gd = dr / self.ELO_PER_GOAL

        # Split total expected goals between teams
        half_total = self.AVG_TOTAL_GOALS / 2.0

        lambda_a = half_total + expected_gd / 2.0
        lambda_b = half_total - expected_gd / 2.0

        # Clamp to reasonable range
        lambda_a = max(self.MIN_LAMBDA, min(self.MAX_LAMBDA, lambda_a))
        lambda_b = max(self.MIN_LAMBDA, min(self.MAX_LAMBDA, lambda_b))

        return lambda_a, lambda_b

    def poisson_prob(self, k: int, lam: float) -> float:
        """Probability of exactly k goals under Poisson(λ)."""
        if lam <= 0:
            return 1.0 if k == 0 else 0.0
        return (math.pow(lam, k) * math.exp(-lam)) / math.factorial(k)

    def simulate_match(self, elo_a: float, elo_b: float) -> Tuple[int, int]:
        """
        Simulate a single match using Poisson distribution.

        Returns:
            Tuple of (goals_a, goals_b)
        """
        lambda_a, lambda_b = self.expected_goals(elo_a, elo_b)
        goals_a = self._sample_poisson(lambda_a)
        goals_b = self._sample_poisson(lambda_b)
        return goals_a, goals_b

    def _sample_poisson(self, lam: float) -> int:
        """Sample from Poisson distribution using inverse transform method."""
        if lam <= 0:
            return 0
        L = math.exp(-lam)
        p = 1.0
        k = 0
        while p > L:
            k += 1
            p *= random.random()
        return k - 1

    def simulate_knockout_match(self, elo_a: float, elo_b: float) -> str:
        """
        Simulate a knockout match including extra time and penalties.

        Returns:
            'A' if team A wins, 'B' if team B wins
        """
        goals_a, goals_b = self.simulate_match(elo_a, elo_b)

        if goals_a > goals_b:
            return 'A'
        elif goals_b > goals_a:
            return 'B'
        else:
            # Extra time / Penalties: 50-50 weighted slightly by ELO
            p_a = self.win_probability(elo_a, elo_b)
            if random.random() < p_a:
                return 'A'
            else:
                return 'B'

    def simulate_group_match(self, elo_a: float, elo_b: float) -> Tuple[int, int, int, int]:
        """
        Simulate a group stage match. Returns (goals_a, goals_b, points_a, points_b).
        Points: 3 for win, 1 for draw, 0 for loss.
        """
        goals_a, goals_b = self.simulate_match(elo_a, elo_b)

        if goals_a > goals_b:
            pts_a, pts_b = 3, 0
        elif goals_b > goals_a:
            pts_a, pts_b = 0, 3
        else:
            pts_a, pts_b = 1, 1

        return goals_a, goals_b, pts_a, pts_b

    def match_outcome_probabilities(self, elo_a: float, elo_b: float, max_goals: int = 8) -> Tuple[float, float, float]:
        """
        Calculate exact probabilities of win/draw/loss using Poisson distribution.

        Returns:
            Tuple of (p_win_a, p_draw, p_win_b)
        """
        lambda_a, lambda_b = self.expected_goals(elo_a, elo_b)
        p_win_a = 0.0
        p_draw = 0.0
        p_win_b = 0.0

        for ga in range(max_goals + 1):
            pa = self.poisson_prob(ga, lambda_a)
            for gb in range(max_goals + 1):
                pb = self.poisson_prob(gb, lambda_b)
                joint = pa * pb
                if ga > gb:
                    p_win_a += joint
                elif gb > ga:
                    p_win_b += joint
                else:
                    p_draw += joint

        # Normalize (truncated Poisson loses some mass)
        total = p_win_a + p_draw + p_win_b
        if total > 0:
            p_win_a /= total
            p_draw /= total
            p_win_b /= total

        return p_win_a, p_draw, p_win_b


if __name__ == "__main__":
    # Quick test
    model = EloPoissonModel(seed=42)
    france, spain = 1877.32, 1876.40
    p_win, p_draw, p_loss = model.match_outcome_probabilities(france, spain)
    print(f"France (1877) vs Spain (1876):")
    print(f"  France win: {p_win*100:.1f}%")
    print(f"  Draw:       {p_draw*100:.1f}%")
    print(f"  Spain win:  {p_loss*100:.1f}%")

    # Simulate 100 matches
    wins = 0
    for _ in range(100):
        ga, gb = model.simulate_match(france, spain)
        if ga > gb:
            wins += 1
    print(f"  Simulated 100 matches: France won {wins}")
