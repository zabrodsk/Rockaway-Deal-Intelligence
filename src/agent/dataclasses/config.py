from pydantic import BaseModel, Field


class Config(BaseModel):
    """Configuration for the iteration process with per-iteration k_best_arguments."""

    n_pro_arguments: int = 5
    n_contra_arguments: int = 5
    k_best_arguments_per_iteration: list[int] = Field(
        default_factory=lambda: [5, 3]
    )  # Different k for each iteration
    max_iterations: int = 2

    # Ranking layer config (optional)
    ranking_weights: dict[str, float] = Field(
        default_factory=lambda: {"strategy_fit": 1 / 3, "team": 1 / 3, "upside": 1 / 3}
    )
    ranking_bucket_thresholds: dict[str, tuple] = Field(
        default_factory=lambda: {
            "priority_review": (75, 55),  # composite >= 75, no dim < 55
            "watchlist": (60, None),  # 60 <= composite < 75
        }
    )

    def get_k_best_for_iteration(self, iteration: int) -> int:
        """Get k_best_arguments for a specific iteration (0-indexed)."""
        if iteration < len(self.k_best_arguments_per_iteration):
            return self.k_best_arguments_per_iteration[iteration]
        # If we exceed defined iterations, use the last k value
        return (
            self.k_best_arguments_per_iteration[-1]
            if self.k_best_arguments_per_iteration
            else 1
        )
