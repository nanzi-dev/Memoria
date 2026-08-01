"""Relationship delta fallback policy tests."""

import pytest

from memoria.core.config import configs
from memoria.core.relationship_delta_policy import resolve_relationship_delta


@pytest.fixture(autouse=True)
def _restore_relationship_delta_config():
    enabled = configs.relationship_delta_enabled
    lower = configs.relationship_delta_min
    upper = configs.relationship_delta_max
    yield
    configs.relationship_delta_enabled = enabled
    configs.relationship_delta_min = lower
    configs.relationship_delta_max = upper


def test_resolve_relationship_delta_zero_llm_plus_warm_text_is_positive():
    delta = resolve_relationship_delta(
        0,
        "今天和你一起散步很开心，谢谢你陪我。",
        "idle",
        20,
        "affinity",
    )
    assert delta > 0
    assert delta <= 10


def test_resolve_relationship_delta_nonzero_llm_is_preserved_and_clipped():
    assert resolve_relationship_delta(3, "普通回复", "idle", 20, "affinity") == 3
    assert resolve_relationship_delta(50, "普通回复", "idle", 20, "affinity") == 10
    assert resolve_relationship_delta(-50, "普通回复", "idle", 20, "affinity") == -10


def test_resolve_relationship_delta_second_warm_turn_still_positive():
    first = resolve_relationship_delta(
        0,
        "我希望和你更亲近，以后也一起走。",
        "idle",
        30,
        "affinity",
    )
    second = resolve_relationship_delta(
        0,
        "我还想和你更亲近，今天也一起吧。",
        "idle",
        31,
        "affinity",
    )
    assert first > 0
    assert second > 0


def test_resolve_relationship_delta_rejection_does_not_increase():
    delta = resolve_relationship_delta(
        0,
        "不用了，我不想说，请你离我远点。",
        "reject",
        20,
        "trust",
    )
    assert delta <= 0


def test_resolve_relationship_delta_neutral_text_does_not_creep():
    delta = resolve_relationship_delta(
        0,
        "please trigger single-keyword-neutral",
        "neutral",
        20,
        "affinity",
    )
    assert delta == 0


def test_resolve_relationship_delta_disabled_keeps_zero_unchanged():
    configs.relationship_delta_enabled = False
    assert (
        resolve_relationship_delta(
            0,
            "今天和你一起散步很开心。",
            "idle",
            20,
            "affinity",
        )
        == 0
    )


def test_resolve_relationship_delta_trust_cues_apply_to_trust_only():
    trust_delta = resolve_relationship_delta(
        0,
        "我愿意把秘密托付给你，我相信你。",
        "idle",
        20,
        "trust",
    )
    affinity_delta = resolve_relationship_delta(
        0,
        "我愿意把秘密托付给你，我相信你。",
        "idle",
        20,
        "affinity",
    )
    assert trust_delta > 0
    assert affinity_delta > 0
