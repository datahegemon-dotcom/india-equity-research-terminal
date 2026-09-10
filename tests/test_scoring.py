"""Tests for the V1.2 Standardized Investment Decision Engine.

Each test names the section of framework 14 it enforces.
"""
import pytest

from app.core.scoring import (
    AUDIT_QUESTIONS,
    CATEGORY_WEIGHTS,
    Action,
    Band,
    DecisionContext,
    MarginOfSafety,
    OverrideRule,
    RawScores,
    classify_margin_of_safety,
    decide,
    expected_value,
)


def scores(**kw):
    base = dict(quality=6, growth=6, earnings=6, valuation=6, moat=6, catalysts=6, risk=6)
    base.update(kw)
    return RawScores(**base)


def perfect():
    return RawScores(**{k: 10 for k in CATEGORY_WEIGHTS})


def audited(**kw):
    kw.setdefault("audit", {q: True for q in AUDIT_QUESTIONS})
    return DecisionContext(**kw)


# --- Section 1: master 100-point score ---------------------------------------

def test_weights_total_one_hundred():
    assert sum(CATEGORY_WEIGHTS.values()) == 100


def test_weighted_contribution_is_raw_over_ten_times_weight():
    d = decide(scores(quality=8), DecisionContext())
    assert d.contributions["quality"] == pytest.approx(16.0)


def test_all_tens_scores_one_hundred():
    assert decide(perfect(), DecisionContext()).total == pytest.approx(100.0)


def test_raw_scores_outside_one_to_ten_are_rejected():
    with pytest.raises(ValueError):
        RawScores(quality=11, growth=5, earnings=5, valuation=5, moat=5, catalysts=5, risk=5)
    with pytest.raises(ValueError):
        RawScores(quality=0, growth=5, earnings=5, valuation=5, moat=5, catalysts=5, risk=5)


# --- Section 10: score bands --------------------------------------------------

@pytest.mark.parametrize(
    "total,band",
    [
        (100.0, Band.HIGH_CONVICTION),
        (85.0, Band.HIGH_CONVICTION),
        (84.9, Band.ATTRACTIVE),
        (75.0, Band.ATTRACTIVE),
        (74.9, Band.WATCHLIST),
        (65.0, Band.WATCHLIST),
        (64.9, Band.CAUTION),
        (50.0, Band.CAUTION),
        (49.9, Band.AVOID),
    ],
)
def test_band_boundaries(total, band):
    assert Band.for_total(total) is band


def test_uniform_tens_lands_high_conviction():
    d = decide(perfect(), DecisionContext(margin_of_safety=MarginOfSafety.HIGH))
    assert d.band is Band.HIGH_CONVICTION
    assert d.action is Action.BUY


# --- Section 11 Rule A: excellent business, excessive valuation ---------------

def test_rule_a_blocks_buy_on_high_quality_low_margin_of_safety():
    d = decide(
        scores(quality=9, growth=9, moat=9, valuation=3, earnings=8, catalysts=7, risk=8),
        DecisionContext(margin_of_safety=MarginOfSafety.LOW),
    )
    assert OverrideRule.A_HIGH_QUALITY_LOW_MOS in d.overrides
    assert d.action is not Action.BUY
    assert d.action in (Action.HOLD, Action.WATCHLIST)


def test_rule_a_needs_all_four_conditions():
    d = decide(
        scores(quality=9, growth=9, moat=7, valuation=3),
        DecisionContext(margin_of_safety=MarginOfSafety.LOW),
    )
    assert OverrideRule.A_HIGH_QUALITY_LOW_MOS not in d.overrides


# --- Section 11 Rule B: cheap but weak ---------------------------------------

def test_rule_b_marks_cheap_but_fundamentally_weak():
    d = decide(
        scores(valuation=9, quality=3, earnings=3, risk=3, growth=3, moat=3, catalysts=3),
        DecisionContext(),
    )
    assert OverrideRule.B_CHEAP_BUT_WEAK in d.overrides
    assert d.action is Action.AVOID


def test_rule_b_allows_watchlist_only_with_turnaround_catalyst():
    d = decide(
        scores(valuation=9, quality=4, earnings=4, risk=4, growth=4, moat=4, catalysts=4),
        DecisionContext(credible_turnaround_catalyst=True),
    )
    assert d.action is Action.WATCHLIST


# --- Section 11 Rule C: extreme valuation -------------------------------------

def test_rule_c_requires_a_multiple_compression_note_before_publishing():
    d = decide(scores(), audited(valuation_extreme=True, margin_of_safety=MarginOfSafety.HIGH))
    assert OverrideRule.C_EXTREME_VALUATION in d.overrides
    assert not d.publishable
    assert any("multiple-compression" in b for b in d.publish_blockers)


def test_rule_c_satisfied_when_note_supplied():
    d = decide(
        scores(),
        audited(
            valuation_extreme=True,
            margin_of_safety=MarginOfSafety.HIGH,
            multiple_compression_note="Trades at 3x its own five-year median EV/EBITDA.",
        ),
    )
    assert d.publishable, d.publish_blockers


# --- Section 12: thesis break -------------------------------------------------

def test_thesis_break_forces_reduce_or_exit_regardless_of_score():
    d = decide(
        perfect(),
        DecisionContext(
            margin_of_safety=MarginOfSafety.HIGH,
            thesis_break=True,
            thesis_break_reasons=["Competitive moat broken"],
        ),
    )
    assert d.total == pytest.approx(100.0)
    assert d.action in (Action.REDUCE, Action.EXIT)


def test_severe_thesis_break_forces_exit():
    d = decide(
        perfect(),
        DecisionContext(
            thesis_break=True,
            thesis_break_severe=True,
            thesis_break_reasons=["Governance failure with evidence"],
        ),
    )
    assert d.action is Action.EXIT


def test_thesis_break_without_a_reason_is_rejected():
    with pytest.raises(ValueError):
        DecisionContext(thesis_break=True).validate()


# --- Section 15: margin of safety --------------------------------------------

@pytest.mark.parametrize(
    "price,base,expected",
    [
        (70.0, 100.0, MarginOfSafety.HIGH),
        (75.0, 100.0, MarginOfSafety.HIGH),
        (80.0, 100.0, MarginOfSafety.MODERATE),
        (90.0, 100.0, MarginOfSafety.MODERATE),
        (95.0, 100.0, MarginOfSafety.LOW),
        (110.0, 100.0, MarginOfSafety.LOW),
        (120.0, 100.0, MarginOfSafety.NEGATIVE),
    ],
)
def test_margin_of_safety_classification(price, base, expected):
    assert classify_margin_of_safety(price, base) is expected


def test_margin_of_safety_needs_a_positive_base_value():
    with pytest.raises(ValueError):
        classify_margin_of_safety(100.0, 0.0)


# --- Section 19: action matrix gates -----------------------------------------

def test_negative_margin_of_safety_caps_action_at_hold():
    d = decide(perfect(), DecisionContext(margin_of_safety=MarginOfSafety.NEGATIVE))
    assert d.action is Action.HOLD


def test_low_margin_of_safety_caps_action_at_accumulate():
    d = decide(perfect(), DecisionContext(margin_of_safety=MarginOfSafety.LOW))
    assert d.action is Action.ACCUMULATE


def test_severe_unresolved_risk_blocks_buy():
    d = decide(
        perfect(),
        DecisionContext(margin_of_safety=MarginOfSafety.HIGH, severe_unresolved_risk=True),
    )
    assert d.action is not Action.BUY


def test_buy_below_eighty_five_requires_written_asymmetry_justification():
    eights = RawScores(quality=8, growth=8, earnings=8, valuation=8, moat=8, catalysts=8, risk=8)

    d = decide(eights, DecisionContext(margin_of_safety=MarginOfSafety.HIGH))
    assert d.total == pytest.approx(80.0)
    assert d.action is Action.ACCUMULATE

    d2 = decide(
        eights,
        DecisionContext(
            margin_of_safety=MarginOfSafety.HIGH,
            asymmetry_justification="Order book covers three years of revenue at current execution.",
        ),
    )
    assert d2.action is Action.BUY


def test_caution_band_does_not_recommend_accumulate():
    d = decide(
        RawScores(**{k: 5 for k in CATEGORY_WEIGHTS}),
        DecisionContext(margin_of_safety=MarginOfSafety.HIGH),
    )
    assert d.band is Band.CAUTION
    assert d.action in (Action.WATCHLIST, Action.AVOID)


# --- Section 18: portfolio overlay -------------------------------------------

def test_portfolio_concentration_can_override_a_high_score():
    d = decide(
        RawScores(**{k: 9 for k in CATEGORY_WEIGHTS}),
        DecisionContext(margin_of_safety=MarginOfSafety.HIGH, portfolio_concentration_breach=True),
    )
    assert d.action is Action.REDUCE


# --- Sections 14 and 22: expected value --------------------------------------

def test_expected_value_weights_scenarios():
    ev = expected_value({"bear": (80.0, 0.25), "base": (100.0, 0.5), "bull": (140.0, 0.25)})
    assert ev == pytest.approx(105.0)


def test_expected_value_rejects_probabilities_that_do_not_sum_to_one():
    with pytest.raises(ValueError):
        expected_value({"bear": (80.0, 0.2), "base": (100.0, 0.2), "bull": (140.0, 0.2)})


def test_expected_value_is_none_when_probabilities_are_absent():
    assert expected_value({"bear": (80.0, None), "base": (100.0, None), "bull": (140.0, None)}) is None


# --- Section 21: score audit gate --------------------------------------------

def test_publish_blocked_until_every_audit_question_is_answered():
    d = decide(scores(), DecisionContext(margin_of_safety=MarginOfSafety.HIGH, audit={"evidence_for_every_score": True}))
    assert not d.publishable
    assert any("audit" in b.lower() for b in d.publish_blockers)


def test_publish_blocked_when_an_audit_question_is_answered_no():
    ctx = audited(margin_of_safety=MarginOfSafety.HIGH)
    ctx.audit["challenged_the_bullish_thesis"] = False
    d = decide(scores(), ctx)
    assert not d.publishable


def test_publish_allowed_when_audit_complete_and_no_blockers():
    d = decide(scores(), audited(margin_of_safety=MarginOfSafety.HIGH))
    assert d.publishable, d.publish_blockers


# --- Section 2: technicals stay outside the hundred --------------------------

def test_technical_score_does_not_enter_the_total():
    plain = decide(scores(), DecisionContext(margin_of_safety=MarginOfSafety.HIGH))
    with_tech = decide(scores(), DecisionContext(margin_of_safety=MarginOfSafety.HIGH, technical_score=9.0))
    assert plain.total == with_tech.total
