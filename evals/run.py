"""Run the eval harness and write evals/report.md.

    uv run --group eval python -m evals.run            # every threshold version
    uv run --group eval python -m evals.run --only v2  # one version

The report is generated: every number in it comes from this run.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path

from evals import matching
from origin_core.settings import get_settings
from origin_worker.embedding import SSCD_DISC_MIXUP, SSCDEmbedder, ensure_weights
from origin_worker.matching.thresholds import CURRENT, THRESHOLDS_DIR, load_thresholds

REPORT = Path(__file__).with_name("report.md")


def _versions() -> list[str]:
    names = sorted(
        p.stem.removeprefix("thresholds.") for p in THRESHOLDS_DIR.glob("thresholds.v*.toml")
    )
    return sorted(names, key=lambda v: int(v.removeprefix("v")))


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def render(results: dict[str, list[matching.Trial]], seconds: float) -> str:
    lines: list[str] = []
    add = lines.append
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%MZ")
    add("# ORIGIN eval report")
    add("")
    add(
        f"Generated {now} by `make eval` in {seconds:.0f} s. "
        f"Embedding model: `{SSCD_DISC_MIXUP.id}`. Current thresholds: `{CURRENT}`."
    )
    add("")
    add("## Matching")
    add("")
    add(
        f"{len(matching.SOURCES)} source photographs (scikit-image sample data), each edited "
        f"{len(matching.EDITS)} ways a repost is edited, plus every ordered pair of different "
        "photographs as negatives. An edit counts as correct when the copy is classified "
        "related and in an "
        "acceptable class; a negative is correct when it is classified unrelated."
    )
    add("")
    add(
        "| Thresholds | Edited copies found (recall) | Right class "
        "| False positives on unrelated pairs |"
    )
    add("| --- | --- | --- | --- |")
    summaries = {v: matching.summarise(t) for v, t in results.items()}
    for version, s in summaries.items():
        add(
            f"| `{version}` | {s.edits_related}/{s.edits} ({_pct(s.edits_related, s.edits)}) | "
            f"{s.edits_correct}/{s.edits} ({_pct(s.edits_correct, s.edits)}) | "
            f"{s.false_positives}/{s.negatives} ({_pct(s.false_positives, s.negatives)}) |"
        )
    add("")

    current = CURRENT if CURRENT in results else next(iter(results))
    trials = results[current]
    s = summaries[current]
    add(f"### By edit (`{current}`)")
    add("")
    add("| Edit | What was done | Found | Right class | Median SSCD |")
    add("| --- | --- | --- | --- | --- |")
    for edit in matching.EDITS:
        total, related, correct = s.by_edit[edit.name]
        add(
            f"| `{edit.name}` | {edit.describe} | {related}/{total} | {correct}/{total} | "
            f"{matching.median_sscd(trials, edit.name):.3f} |"
        )
    add("")
    add(
        f"SSCD separation: the lowest score of an edited copy that was found is "
        f"{s.sscd_related_min:.3f}; unrelated pairs score at most {s.sscd_negative_max:.3f} "
        f"(99th percentile {s.sscd_negative_p99:.3f})."
    )
    add("")

    hard = [
        t for t in trials if t.kind == "negative" and (t.source, t.other) in matching.HARD_NEGATIVES
    ]
    if hard:
        add("Hard negative (the same scene from a slightly different position):")
        add("")
        for t in hard:
            verdict = "unrelated (correct)" if t.correct else f"{t.result.match_class} (wrong)"
            add(f"- `{t.source}` vs `{t.other}`: {verdict}; {t.result.reason}")
        add("")

    misses = [t for t in trials if t.kind == "edit" and not t.correct]
    add(f"### Edited copies not handled correctly (`{current}`): {len(misses)}")
    add("")
    if misses:
        add("| Source | Edit | Got | Why |")
        add("| --- | --- | --- | --- |")
        for t in misses:
            got = t.result.match_class.value if t.result.match_class else "unrelated"
            add(f"| `{t.source}` | `{t.other}` | {got} | {t.result.reason} |")
        add("")
    false_pos = [t for t in trials if t.kind == "negative" and not t.correct]
    add(f"### False positives (`{current}`): {len(false_pos)}")
    add("")
    for t in false_pos:
        add(f"- `{t.source}` vs `{t.other}`: {t.result.match_class}; {t.result.reason}")
    if false_pos:
        add("")
    add("## How to read this")
    add("")
    add(
        "- A false positive is worse than a miss: it would put an unrelated picture into the "
        "evidence. Thresholds are tuned to keep false positives at zero first, then raise recall."
    )
    add(
        "- The sample photographs are small (mostly 512 px or less). Real reposts start from "
        "larger originals, so recall on heavy crops here is a floor, not a ceiling."
    )
    add(
        "- Threshold files are never edited in place. A recalibration adds a new version, reruns "
        "this report, and every stored sighting keeps the version that classified it."
    )
    add("")
    return "\n".join(lines)


async def _embedder() -> SSCDEmbedder:
    return SSCDEmbedder(await ensure_weights(get_settings().models_dir))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="evals.run")
    parser.add_argument("--only", help="evaluate one threshold version, e.g. v2")
    args = parser.parse_args(argv)
    versions = [args.only] if args.only else _versions()
    started = time.monotonic()
    embedder = asyncio.run(_embedder())
    pairs = matching.prepare(embedder, progress=print)
    results = {v: matching.run(pairs, load_thresholds(v)) for v in versions}
    report = render(results, time.monotonic() - started)
    REPORT.write_text(report, encoding="utf-8")
    print(report.split("### By edit")[0])
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    main()
