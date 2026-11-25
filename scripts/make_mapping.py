"""Generate docs/QUESTIONNAIRE_MAPPING.md from data/questions.yaml."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from splash_app.i18n import load_questions  # noqa: E402


def main() -> None:
    data = load_questions()
    lines = [
        "# Questionnaire mapping",
        "",
        f"Generated from `data/questions.yaml` (version {data['meta']['version']}). Do not edit by hand, run `python scripts/make_mapping.py`.",
        "",
        "`draft` = from your questionnaire draft v1, `added` = added for the calculation or the research design. "
        "`feeds` says whether the answer drives the calculation, the research evaluation, or the contact table.",
        "",
    ]
    for step, info in data["steps"].items():
        qs = [q for q in data["questions"] if q["step"] == step]
        if not qs:
            continue
        lines += [f"## Step {step}: {info['title_en']}", "", "| id | type | origin | feeds | required | question (EN) |", "|---|---|---|---|---|---|"]
        for q in qs:
            label = q["label_en"].replace("|", "/")
            lines.append(f"| `{q['id']}` | {q['type']} | {q['origin']} | {q['feeds']} | {'yes' if q.get('required') else ''} | {label} |")
        lines.append("")
    n_draft = sum(q["origin"] == "draft" for q in data["questions"])
    lines.append(f"Total: {len(data['questions'])} items, {n_draft} from the draft, {len(data['questions']) - n_draft} added.")
    out = ROOT / "docs" / "QUESTIONNAIRE_MAPPING.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
