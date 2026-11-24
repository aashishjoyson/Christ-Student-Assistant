from app.eval.parity import accuracy_by_slice, gap, regressions


def test_accuracy_gap_and_regressions() -> None:
    acc = accuracy_by_slice([("a", True), ("a", True), ("b", True), ("b", False), ("c", False)])
    assert acc == {"a": 1.0, "b": 0.5, "c": 0.0}
    assert gap(acc) == 1.0
    assert gap({}) == 0.0
    assert regressions({"a": 1.0, "b": 0.4}, {"a": 1.0, "b": 0.5}) == {"b": (0.5, 0.4)}
    assert regressions({"a": 1.0, "b": 0.6}, {"a": 1.0, "b": 0.5}) == {}  # improving is fine
    assert regressions({"a": 1.0}, {"a": 1.0, "gone": 0.3}) == {"gone": (0.3, 0.0)}  # a missing slice counts as a drop
