"""Quality control refuses to ship a broken file."""
from __future__ import annotations

from engine.qc import Finding, verdict


class TestVerdict:
    def test_blocking_finding_stops_the_export(self):
        v = verdict([Finding("x", "blocking", "broken")])
        assert v["can_export"] is False and len(v["blocking"]) == 1

    def test_warnings_alone_do_not_stop_it(self):
        v = verdict([Finding("x", "warning", "odd"), Finding("y", "ok", "fine")])
        assert v["can_export"] is True and len(v["warnings"]) == 1

    def test_all_checks_are_reported_not_just_failures(self):
        v = verdict([Finding("a", "ok", ""), Finding("b", "warning", ""),
                     Finding("c", "blocking", "")])
        assert len(v["checks"]) == 3
