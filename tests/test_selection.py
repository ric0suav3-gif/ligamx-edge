from __future__ import annotations

from model.selection import balanced_score, fair_band


def test_fair_bands() -> None:
    assert fair_band(1.75) == "CORE"
    assert fair_band(2.9) == "EXTENDED"
    assert fair_band(5.0) == "LONGSHOT"


def test_core_market_beats_extreme_longshot_when_other_inputs_match() -> None:
    core = balanced_score(
        fair_odds=1.80,
        consensus_ev=0.18,
        books=3,
        reliability="MEDIUM",
        market_type="home_total",
        source="FULL_MODEL",
    )
    longshot = balanced_score(
        fair_odds=5.80,
        consensus_ev=2.00,
        books=3,
        reliability="LOW",
        market_type="home_total",
        source="FULL_MODEL",
    )
    assert core.score > longshot.score
    assert "LONGSHOT" in longshot.flags
    assert "EXTREME_EV" in longshot.flags


def test_joint_and_proxy_flags_are_explicit() -> None:
    grade = balanced_score(
        fair_odds=1.90,
        consensus_ev=0.12,
        books=2,
        reliability="LOW",
        market_type="handicap",
        source="ONE_SIDED_FALLBACK",
    )
    assert "JOINT_INDEPENDENCE" in grade.flags
    assert "ONE_SIDED_PROXY" in grade.flags
    assert "LOW_RELIABILITY" in grade.flags
