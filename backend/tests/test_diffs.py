from backend.diffs import diff


def test_a_diff_marks_each_line():
    old = "Decide the claim.\nUse the wording.\nRecord it."
    new = "Decide the claim.\nUse the wording and the manual.\nRecord it.\nCheck it."
    assert [(line.change, line.text) for line in diff(old, new)] == [
        ("unchanged", "Decide the claim."),
        ("removed", "Use the wording."),
        ("added", "Use the wording and the manual."),
        ("unchanged", "Record it."),
        ("added", "Check it."),
    ]


def test_no_change_is_all_unchanged():
    assert {line.change for line in diff("a\nb", "a\nb")} == {"unchanged"}


def test_from_nothing_every_line_is_added():
    assert [line.change for line in diff("", "a\nb")] == ["added", "added"]
