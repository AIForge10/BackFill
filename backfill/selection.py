"""Record the out-of-sample specification from completed in-sample bundles.

The holdout always evaluates the registered primary. Choosing the variant with
the best in-sample Sharpe would be a best-of-N selection, so other variants are
only recorded (metrics and placebo p-values) for the note's variant disclosure.
The placebo gate (control HAC p >= .05) is reported, not used to switch variants;
it does NOT establish economic equivalence or validate the causal placebo claim.
"""
import argparse
import json
import math
from pathlib import Path

from backfill.prices import sha256


def choose(results):
    candidates = []
    for identity_file in sorted(Path(results).glob("*/identity.json")):
        status_file = identity_file.parent / "status.json"
        if not status_file.exists() or json.loads(status_file.read_text()).get("status") != "completed":
            continue
        identity = json.loads(identity_file.read_text())
        if identity["settings"]["final"] or identity.get("diagnostic_leave_out"):
            continue
        variant = identity["selected_variant"]
        winner_file = identity_file.parent / variant / "winner/costs1/metrics.json"
        control_file = identity_file.parent / variant / "placebo/costs1/metrics.json"
        if not winner_file.exists() or not control_file.exists():
            continue
        # Require the costs-doubled bundle too: partial runs cannot win selection.
        if not all((identity_file.parent / variant / role / "costs2/metrics.json").exists()
                   for role in ["winner", "placebo"]):
            continue
        winner, control = json.loads(winner_file.read_text()), json.loads(control_file.read_text())
        sharpe, p_value = winner.get("sharpe"), control.get("inference", {}).get("p_value")
        if sharpe is None or p_value is None or not math.isfinite(sharpe) or not math.isfinite(p_value):
            continue
        candidates.append(dict(variant=variant, net_sharpe=sharpe, placebo_p=p_value,
                               bundle=str(identity_file.parent.resolve()), identity=identity,
                               metrics_hashes={str(p.resolve()): sha256(p) for p in [winner_file, control_file]}))
    primary = [c for c in candidates if c["variant"] == "primary"]
    if not primary:
        raise ValueError("No completed in-sample primary bundle (with both cost levels). Run it before freezing.")
    # Different source/code/cache vintages cannot be pooled in one disclosure.
    signatures = {json.dumps(c["identity"]["files"], sort_keys=True) for c in candidates}
    if len(signatures) != 1:
        raise ValueError("Bundles use different code/data vintages. Evaluate one frozen vintage before freezing.")
    candidates.sort(key=lambda c: (c["variant"] != "primary", c["variant"], c["bundle"]))
    return dict(selected=primary[-1],
                disclosed_variants=[dict(variant=c["variant"], net_sharpe=c["net_sharpe"], placebo_p=c["placebo_p"],
                                         placebo_gate_passed=c["placebo_p"] >= .05, bundle=c["bundle"])
                                    for c in candidates],
                rule="the registered primary is the only out-of-sample specification; other variants are disclosed, not selected",
                warning="nonlisted controls are not verified nonmanufacturers; nonsignificance is not equivalence")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", type=Path, default=Path("results/backfill"))
    ap.add_argument("--output", type=Path, default=Path("data/processed/backfill/selection.json"))
    args = ap.parse_args()
    record = choose(args.results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n")
    print(f"Selection recorded in {args.output}; no new strategy evaluated.")


if __name__ == "__main__":
    main()
