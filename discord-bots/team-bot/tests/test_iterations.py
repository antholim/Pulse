from datetime import date

from team_bot.domain.iterations import (
    build_iterations,
    find_iteration,
    iteration_for,
    release_for,
)

from conftest import RELEASES, make_milestone


def test_iterations_are_consecutive(iterations):
    first, second = iterations[0], iterations[1]
    assert (first.start, first.end) == (date(2026, 9, 23), date(2026, 10, 6))
    assert (second.start, second.end) == (date(2026, 10, 7), date(2026, 10, 20))


def test_due_date_belongs_to_its_iteration(iterations):
    assert iteration_for(date(2026, 10, 6), iterations).number == 1
    assert iteration_for(date(2026, 10, 7), iterations).number == 2
    assert iteration_for(date(2026, 9, 1), iterations) is None
    assert iteration_for(date(2027, 1, 1), iterations) is None


def test_non_iteration_and_undated_milestones_are_ignored():
    milestones = [
        make_milestone(1, "2026-10-06"),
        make_milestone(9, "2026-10-10", title="Demo day"),
        make_milestone(2, None),
    ]
    assert [it.number for it in build_iterations(milestones)] == [1]


def test_iterations_are_ordered_by_number_not_input_order():
    milestones = [make_milestone(2, "2026-10-20"), make_milestone(1, "2026-10-06")]
    assert [it.number for it in build_iterations(milestones)] == [1, 2]


def test_out_of_order_due_dates_keep_a_one_day_window():
    milestones = [make_milestone(1, "2026-10-20"), make_milestone(2, "2026-10-06")]
    second = build_iterations(milestones)[1]
    assert second.start == second.end == date(2026, 10, 6)


def test_find_iteration(iterations):
    assert find_iteration(3, iterations).title == "Iteration 3"
    assert find_iteration(99, iterations) is None


def test_release_window_spans_its_iterations(iterations):
    window = release_for(find_iteration(2, iterations), iterations, RELEASES)
    assert window.name == "Release 1"
    assert (window.start, window.end) == (date(2026, 9, 23), date(2026, 11, 17))
    assert (window.first_iteration, window.last_iteration) == (1, 4)

    release2 = release_for(find_iteration(5, iterations), iterations, RELEASES)
    assert release2.name == "Release 2"
    assert release2.start == date(2026, 11, 18)


def test_iteration_outside_every_release(iterations):
    assert release_for(find_iteration(5, iterations), iterations, RELEASES[:1]) is None
