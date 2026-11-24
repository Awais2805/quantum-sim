"""Time ONLY the fusion pass (no simulation) for the fusion methods used in the meeting tables.

No statevector is ever allocated, so this runs at any qubit count on any machine.
Uses the same circuit builders and fusion functions as quest_bench.py / fusion_bench.py,
and an existing QuEST cost table for the cost-model and measured-cost fusion (never calibrates).

    ../.venv/bin/python transpile_time.py                       # defaults below
    ../.venv/bin/python transpile_time.py --ns 16,20,24 --seeds 1234 --reps 3

Writes <out>/transpile_times.csv and <out>/TRANSPILE.md.
"""
import argparse
import csv
import platform
import socket
import statistics
import time
from pathlib import Path

import fusion_bench as fb
from dp_fusion import fuse_dp
from quest_bench import QuestCosts
from quest_ops import QUEST_BASIS

HERE = Path(__file__).resolve().parent
DEFAULT_TABLE = HERE / "results" / "meeting_n24" / "cost_table_v2_qbench_quest_t2_n24.json"


def methods(widths, costs):
    """(label, k, fn(qc) -> fused qc) for every fusion method in the meeting tables."""
    out = []
    for mode in ("horizontal", "vertical"):
        for k in widths:
            out.append((f"{mode}, greedy", k, lambda qc, m=mode, k=k: fb.fuse(qc, m, k)))
            out.append((f"{mode}, cost model", k, lambda qc, m=mode, k=k: fb.fuse(qc, m, k, costs)))
    out.append(("measured-cost fusion", 0, lambda qc: fuse_dp(qc, "dp", costs.table, max_qubit=5)))
    return out


def cpu_name():
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "?"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--circuits", default="qft,rqc")
    p.add_argument("--ns", default="16,20,24,26,28,30,32,34")
    p.add_argument("--seeds", default="1234,1000,2000", help="rqc seeds (circuit seed = seed + n)")
    p.add_argument("--widths", default="2,3,4")
    p.add_argument("--reps", type=int, default=3, help="timed repeats per method; the minimum is kept")
    p.add_argument("--table", type=Path, default=DEFAULT_TABLE, help="QuEST cost table JSON (not recalibrated)")
    p.add_argument("--out", type=Path, default=HERE / "results" / f"transpile_{socket.gethostname()}")
    a = p.parse_args()
    circuits = [c for c in a.circuits.split(",") if c]
    ns = [int(x) for x in a.ns.split(",") if x]
    seeds = [int(x) for x in a.seeds.split(",") if x]
    widths = [int(x) for x in a.widths.split(",") if x]

    import json
    table = json.loads(a.table.read_text())
    n_cal = int(a.table.stem.rsplit("_n", 1)[1]) if "_n" in a.table.stem else 0
    costs = QuestCosts(table, n_cal)
    a.out.mkdir(parents=True, exist_ok=True)

    fields = ["circuit", "seed", "n", "gates_in", "build_s", "method", "k", "gates_out", "fuse_min_s",
              "fuse_med_s", "reps", "error"]
    rows = []
    for c in circuits:
        for seed in (seeds if c == "rqc" else [0]):
            for n in ns:
                t0 = time.perf_counter()
                base = fb.build_circuit(c, n, 0, seed, basis=QUEST_BASIS)
                build_s = time.perf_counter() - t0
                gates_in = len(base.data)
                line = [f"{c} seed={seed} n={n:2d} gates={gates_in:5d}"]
                for label, k, fn in methods(widths, costs):
                    times, out, err = [], None, ""
                    try:
                        for _ in range(a.reps):
                            t0 = time.perf_counter()
                            out = fn(base)
                            times.append(time.perf_counter() - t0)
                    except Exception as e:  # e.g. a cost-table key missing; record, don't stop
                        err = f"{type(e).__name__}: {e}"[:200]
                    rows.append({"circuit": c, "seed": seed, "n": n, "gates_in": gates_in,
                                 "build_s": f"{build_s:.6f}", "method": label, "k": k,
                                 "gates_out": len(out.data) if out is not None and not err else "",
                                 "fuse_min_s": f"{min(times):.6f}" if times and not err else "",
                                 "fuse_med_s": f"{statistics.median(times):.6f}" if times and not err else "",
                                 "reps": len(times), "error": err})
                    if not err:
                        line.append(f"{label[:4]}{label.split(', ')[-1][:2] if ',' in label else ''}"
                                    f"{k or ''}={min(times):.3f}")
                    else:
                        line.append(f"{label} k={k}: ERROR")
                print("  ".join(line), flush=True)

    with open(a.out / "transpile_times.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    # summary: per circuit, method, k -> fusion time per n (mean over seeds of the per-seed minimum)
    md = [f"# Fusion-pass time only (no simulation)", "",
          f"Machine: `{socket.gethostname()}` ({cpu_name()}), single Python process. "
          f"Time = fastest of {a.reps} repeats, averaged over rqc seeds {', '.join(map(str, seeds))}. "
          f"Cost table: `{a.table.name}` (QuEST, measured on qbench; used only to decide what to fuse).", ""]
    for c in circuits:
        sub = [r for r in rows if r["circuit"] == c]
        md += [f"## {c.upper()}", "",
               "| method | k | " + " | ".join(f"n={n}" for n in ns) + " |",
               "|---|---:|" + "---:|" * len(ns),
               "| *gates in circuit* | | " + " | ".join(
                   f"{statistics.fmean(r['gates_in'] for r in sub if r['n'] == n and r['method'] == 'measured-cost fusion'):.0f}"
                   for n in ns) + " |"]
        for label, k, _ in methods(widths, costs):
            cells = []
            for n in ns:
                ts = [float(r["fuse_min_s"]) for r in sub
                      if r["n"] == n and r["method"] == label and r["k"] == k and r["fuse_min_s"]]
                cells.append(f"{statistics.fmean(ts):.3f} s" if ts else "error")
            md.append(f"| {label} | {k or '–'} | " + " | ".join(cells) + " |")
        md.append("")
    errs = [r for r in rows if r["error"]]
    if errs:
        md += ["## Errors", ""] + [f"- {r['circuit']} seed={r['seed']} n={r['n']} {r['method']} k={r['k']}: "
                                    f"{r['error']}" for r in errs] + [""]
    (a.out / "TRANSPILE.md").write_text("\n".join(md))
    print(f"wrote {a.out / 'transpile_times.csv'} and {a.out / 'TRANSPILE.md'}")


if __name__ == "__main__":
    main()
