from __future__ import annotations

from app.services.qualities import effective_max_width, normalize_quality


def test_quality_widths_without_admin_cap() -> None:
    assert effective_max_width("reading", 0) == 1200
    assert effective_max_width("standard", 0) == 2000
    assert effective_max_width("appreciation", 0) == 2800
    assert effective_max_width("research", 0) == 0


def test_admin_cap_limits_resized_qualities_only() -> None:
    assert effective_max_width("reading", 1000) == 1000
    assert effective_max_width("standard", 1800) == 1800
    assert effective_max_width("appreciation", 2500) == 2500
    assert effective_max_width("research", 2500) == 0


def test_unknown_quality_falls_back_to_research() -> None:
    assert normalize_quality("poster") == "research"
    assert effective_max_width("poster", 0) == 0
