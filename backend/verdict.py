"""UnderCover's rule for keeping a new version of the claim agent, as the lab's
compare and keep_or_roll_back: from its held-out scores against the current
version's, and the business's objectives, noise and tolerance."""

from typing import NamedTuple

from backend.models import Limits, Objectives, Scores

# Compared as a difference: 0.1 is ten points of accuracy.
DIFFERENCES = ("accuracy", "grade")
# Compared as a fraction of the old value: 0.15 is 15%, and 1.0 is double.
FRACTIONS = ("model_cost_per_claim", "seconds_per_claim")
NO_GRADE = "it has no grade"
RULE = (
    "A new version is kept when it meets the objectives, at least one measure "
    "improves by more than its noise and none gets worse by more than its tolerance"
)


class Verdict(NamedTuple):
    kept: bool
    why: str


def compare(
    new: Scores, old: Scores, noise: Limits, tolerance: Limits
) -> tuple[list[str], list[str]]:
    """Return the measures that got better by more than their noise, and those that
    got worse by more than their tolerance. A missing grade on either side is
    left out."""
    better, worse = [], []
    for name in DIFFERENCES:
        after, before = getattr(new, name), getattr(old, name)
        if after is None or before is None:
            continue
        if after > before + getattr(noise, name):
            better.append(name)
        if after < before - getattr(tolerance, name):
            worse.append(name)
    for name in FRACTIONS:
        after, before = getattr(new, name), getattr(old, name)
        if after < before * (1 - getattr(noise, name)):
            better.append(name)
        if after > before * (1 + getattr(tolerance, name)):
            worse.append(name)
    return better, worse


def keep_or_roll_back(
    new: Scores,
    old: Scores,
    objectives: Objectives,
    noise: Limits,
    tolerance: Limits,
) -> Verdict:
    """Keep a version that meets the objectives, improves at least one measure by
    more than its noise and makes none worse by more than its tolerance."""
    if new.grade is None:
        return Verdict(False, NO_GRADE)
    missed = [
        name
        for name, floor in objectives.model_dump().items()
        if getattr(new, name) < floor
    ]
    if missed:
        return Verdict(False, f"it missed the objectives on {' and '.join(missed)}")
    better, worse = compare(new, old, noise, tolerance)
    if worse:
        return Verdict(False, f"{' and '.join(worse)} got worse")
    if not better:
        return Verdict(False, "no measure improved by more than the noise")
    return Verdict(True, f"{' and '.join(better)} improved")
