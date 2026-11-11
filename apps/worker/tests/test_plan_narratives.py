from origin_core.llm.prompts.narrative import NarrativeOut, NarrativesOut
from origin_worker.branch import plan_narratives


def _n(label: str, ids: list[str], contradicts: bool, dimension: str | None = None) -> NarrativeOut:
    return NarrativeOut(
        label=label,
        summary=label,
        claim_ids=ids,
        contradicts_earliest=contradicts,
        contradiction=dimension,  # pyright: ignore[reportArgumentType]
    )


def test_only_contradictions_open_branches() -> None:
    out = NarrativesOut(
        narratives=[
            _n("Vague repost", ["c3"], contradicts=False),
            _n("Florida", ["c4"], contradicts=True, dimension="place"),
            _n("Valencia", ["c1", "c2"], contradicts=False),
        ]
    )
    planned = plan_narratives(out)
    assert [(p.label, p.claim_ids, p.reason) for p in planned] == [
        ("Valencia", ["c1", "c2", "c3"], None),
        ("Florida", ["c4"], "contradicts the earliest narrative on place"),
    ]


def test_root_is_where_c1_is_even_if_listed_last() -> None:
    out = NarrativesOut(narratives=[_n("B", ["c2"], True, "date"), _n("A", ["c1"], False)])
    assert [p.label for p in plan_narratives(out)] == ["A", "B"]
