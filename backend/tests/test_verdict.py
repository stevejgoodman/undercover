"""UnderCover's rule, with measures worked out by hand against the lab's settings:
accuracy and the grade compared as differences, cost and time as fractions of the
old value."""

import pytest

from backend.models import Limits, Objectives, Scores
from backend.verdict import keep_or_roll_back

OBJECTIVES = Objectives(accuracy=0.6, grade=1.0)
NOISE = Limits(
    accuracy=0.1, grade=0.15, model_cost_per_claim=0.15, seconds_per_claim=0.15
)
TOLERANCE = Limits(
    accuracy=0.1, grade=0.15, model_cost_per_claim=1.0, seconds_per_claim=0.25
)


def scores(accuracy, grade, cost, seconds):
    return Scores(
        runs=2,
        decision_accuracy=accuracy,
        accuracy=accuracy,
        cost_of_mistakes=0,
        straight_through=1,
        model_cost_per_claim=cost,
        seconds_per_claim=seconds,
        grade=grade,
    )


BEFORE = scores(0.72, 1.80, 0.0010, 20)


@pytest.mark.parametrize(
    ("after", "kept", "why"),
    [
        # 0.84 > 0.72 + 0.1; the grade within 0.15; cost under double; time under 25%
        (scores(0.84, 1.85, 0.0018, 22), True, "accuracy improved"),
        # accuracy improved, but 1.60 < 1.80 - 0.15
        (scores(0.84, 1.60, 0.0010, 20), False, "grade got worse"),
        # 0.74 < 0.82 and 1.90 < 1.95: nothing beats the noise
        (
            scores(0.74, 1.90, 0.0010, 20),
            False,
            "no measure improved by more than the noise",
        ),
        # below the 0.6 floor, however cheap and quick
        (
            scores(0.58, 2.2, 0.0005, 10),
            False,
            "it missed the objectives on accuracy",
        ),
        # 0.00084 < 0.0010 × (1 - 0.15) = 0.00085
        (scores(0.72, 1.80, 0.00084, 20), True, "model_cost_per_claim improved"),
        # 25.5 > 20 × (1 + 0.25) = 25
        (scores(0.72, 1.80, 0.0010, 25.5), False, "seconds_per_claim got worse"),
        (scores(0.84, None, 0.0010, 20), False, "it has no grade"),
    ],
)
def test_keep_or_roll_back(after, kept, why):
    assert keep_or_roll_back(after, BEFORE, OBJECTIVES, NOISE, TOLERANCE) == (kept, why)


def test_every_measure_that_improved_is_named():
    after = scores(0.84, 2.0, 0.0005, 12)
    verdict = keep_or_roll_back(after, BEFORE, OBJECTIVES, NOISE, TOLERANCE)
    assert verdict == (
        True,
        "accuracy and grade and model_cost_per_claim and seconds_per_claim improved",
    )


def test_a_grade_below_its_floor_misses_the_objectives():
    after = scores(0.84, 0.9, 0.0010, 20)
    assert keep_or_roll_back(after, BEFORE, OBJECTIVES, NOISE, TOLERANCE) == (
        False,
        "it missed the objectives on grade",
    )
