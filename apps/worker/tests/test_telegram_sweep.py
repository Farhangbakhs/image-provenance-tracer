"""Sweep keywords and the optional stage's place in the run monitor."""

from __future__ import annotations

from origin_core.pipeline.registry import stage_order
from origin_worker.telegram.sweep import keywords


def test_keywords_are_frequent_content_words_in_first_seen_order() -> None:
    titles = [
        "Floods sweep through Valencia",
        "Valencia counts the cost of the floods",
        "Photo: hurricane damage in Florida",
    ]
    assert keywords(titles, 2) == ["floods", "valencia"]
    assert keywords(titles, 4) == ["floods", "valencia", "sweep", "counts"]
    assert keywords(["Photo of the day 2024"], 2) == []


def test_stage_order_shows_the_sweep_only_when_it_ran() -> None:
    assert "telegram_sweep" not in stage_order(["ingest", "date"])
    order = stage_order(["telegram_sweep"])
    assert order[order.index("date") + 1] == "telegram_sweep"
