"""Tests for honest terminal job status (A5).

Previously a job reported status="completed", progress=1.0 regardless of render
outcomes, so a paper whose visualizations all failed — or that generated none at
all — showed the reader a green checkmark over a page with no animations.
"""

from jobs.worker import resolve_terminal_job_status


def test_all_renders_succeeded_is_completed():
    status, step, error = resolve_terminal_job_status(3, 3)
    assert status == "completed"
    assert step == "Complete"
    assert error is None


def test_partial_failure_completes_but_reports_the_failures():
    status, step, error = resolve_terminal_job_status(2, 3)
    assert status == "completed"  # some videos exist — the page is worth showing
    assert "1 visualization(s) failed" in step
    assert error is None


def test_all_renders_failed_is_not_reported_as_success():
    status, step, error = resolve_terminal_job_status(0, 3)
    assert status == "failed"
    assert step == "All visualizations failed to render"
    assert error is not None and "All 3 visualization(s) failed" in error


def test_no_visualizations_generated_is_not_reported_as_success():
    status, step, error = resolve_terminal_job_status(0, 0)
    assert status == "failed"
    assert step == "No valid visualizations generated"
    # The paper text is still readable — the message must say so.
    assert error is not None and "paper text is still available" in error


def test_single_visualization_success_and_failure():
    assert resolve_terminal_job_status(1, 1)[0] == "completed"
    assert resolve_terminal_job_status(0, 1)[0] == "failed"
