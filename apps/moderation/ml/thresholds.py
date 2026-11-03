from dataclasses import dataclass

import numpy as np

STEP = 0.05
GAP = 0.01


@dataclass(frozen=True)
class ThresholdReport:
    photo_electronics: float
    photo_other: float
    electronics_passed: float
    other_passed: float
    other_caught: float
    electronics_caught: float
    auc: float
    table: list[tuple[float, float, float]]

    @property
    def electronics_review(self) -> float:
        return 1 - self.electronics_passed - self.electronics_caught

    @property
    def other_review(self) -> float:
        return 1 - self.other_passed - self.other_caught


def _share(scores: np.ndarray, condition) -> float:
    return float(condition(scores).mean()) if len(scores) else 0.0


def _auc(electronics: np.ndarray, other: np.ndarray) -> float:
    wins = (electronics[:, None] > other[None, :]).sum()
    ties = (electronics[:, None] == other[None, :]).sum()
    return float((wins + ties / 2) / (len(electronics) * len(other)))


def tune(electronics, other, *, max_false_pass: float, max_false_reject: float) -> ThresholdReport:
    electronics = np.asarray(electronics, dtype=float)
    other = np.asarray(other, dtype=float)
    if not len(electronics) or not len(other):
        raise ValueError("Нужны фото обоих классов.")

    photo_electronics = round(float(np.quantile(other, 1 - max_false_pass, method="higher")), 3)
    photo_electronics = min(1.0, photo_electronics + 0.001)
    photo_other = round(float(np.quantile(electronics, max_false_reject, method="lower")), 3)
    photo_other = max(0.0, min(photo_other - 0.001, round(photo_electronics - GAP, 3)))

    table = [
        (
            round(threshold, 2),
            _share(electronics, lambda scores, t=threshold: scores >= t),
            _share(other, lambda scores, t=threshold: scores >= t),
        )
        for threshold in np.arange(STEP, 1, STEP)
    ]
    return ThresholdReport(
        photo_electronics=photo_electronics,
        photo_other=photo_other,
        electronics_passed=_share(electronics, lambda scores: scores >= photo_electronics),
        other_passed=_share(other, lambda scores: scores >= photo_electronics),
        other_caught=_share(other, lambda scores: scores <= photo_other),
        electronics_caught=_share(electronics, lambda scores: scores <= photo_other),
        auc=_auc(electronics, other),
        table=table,
    )
