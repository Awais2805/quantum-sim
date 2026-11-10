#!/usr/bin/env python3
"""Average the random-circuit (RQC) comparison over several random circuits (seeds).

    python seed_summary.py results/rqc_seeds_n24 results/meeting_n24 [--out SUMMARY.md]

Reads every rqc*.csv in the given directories (fusion_bench.py / quest_bench.py output, as written
by rqc_seeds.sh and meeting_run.sh). The seed comes from 'seed<digits>' in the file name; files
without one (the meeting run) get --default-seed (1234). For each seed, every configuration's time
is turned into a speedup vs that seed's **Aer, no fusion** (and vs the same simulator's no
fusion); the tables then give the geometric mean over seeds with the min-max range, so each random
circuit counts equally whatever its absolute run time.
"""
import argparse
import csv
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def label(row):
    mode, k, cm = row["mode"], int(row["k"]), int(row.get("cost_model") or 0)
    if mode == "none":
        return "no fusion", "–"
    if mode == "aer":
        return "Aer built-in fusion", "–"
    if mode.startswith("dp"):
        return "measured-cost fusion", "–"
    if mode == "control":
        return "control", "–"
    return f"{mode}, {'cost model' if cm else 'greedy'}", str(k)


ORDER = ["no fusion", "Aer built-in fusion", "measured-cost fusion",
         "horizontal, greedy", "horizontal, cost model", "vertical, greedy", "vertical, cost model"]


def load(dirs, default_seed):
    data = defaultdict(dict)   # seed -> (backend, method, k) -> (time, ops)
    ns = set()
    for d in map(Path, dirs):
        for f in sorted(d.glob("rqc*.csv")):
            m = re.search(r"seed(\d+)", f.stem)
            seed = int(m.group(1)) if m else default_seed
            for r in csv.DictReader(open(f, newline="")):
                if r.get("circuit", "rqc") != "rqc":
                    continue
                ns.add(int(r["n"]))
                key = (r.get("backend") or "aer", *label(r))
                t = float(r["sim_min_s"])
                if key not in data[seed] or t < data[seed][key][0]:
                    data[seed][key] = (t, int(r["ops"]))
    return data, ns


def gmean(xs):
    return math.exp(statistics.fmean(math.log(x) for x in xs))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--default-seed", type=int, default=1234)
    ap.add_argument("--out")
    a = ap.parse_args()

    data, ns = load(a.dirs, a.default_seed)
    seeds = sorted(s for s, d in data.items() if ("aer", "no fusion", "–") in d)
    if not seeds:
        sys.exit("no seed has an 'Aer, no fusion' row yet")
    if len(ns) > 1:
        print(f"warning: mixed sizes {sorted(ns)}", file=sys.stderr)
    n = max(ns)

    keys = sorted({k for s in seeds for k in data[s] if k[1] != "control"},
                  key=lambda k: (k[0] != "aer", ORDER.index(k[1]) if k[1] in ORDER else 99, k[2]))
    lines = [f"# Random circuits at {n} qubits, averaged over {len(seeds)} circuits", "",
             f"Seeds (circuit seed = seed + {n}): {', '.join(map(str, seeds))}. "
             "Speedups are per circuit, then combined with the geometric mean; [min–max] is the range "
             "over circuits. Times are sim_min_s.", "",
             "| simulator | method | k | circuits | speedup vs Aer, no fusion | range | "
             "speedup vs same simulator, no fusion | range | mean time (s) | mean gates |",
             "|---|---|---:|---:|---:|---|---:|---|---:|---:|"]
    best = None
    for key in keys:
        backend, method, k = key
        have = [s for s in seeds if key in data[s] and (backend, "no fusion", "–") in data[s]]
        if not have:
            continue
        vs_aer = [data[s][("aer", "no fusion", "–")][0] / data[s][key][0] for s in have]
        vs_own = [data[s][(backend, "no fusion", "–")][0] / data[s][key][0] for s in have]
        g = gmean(vs_aer)
        if best is None or g > best[0]:
            best = (g, f"{'Aer' if backend == 'aer' else 'QuEST'} · {method}" + (f" k={k}" if k != "–" else ""))
        lines.append(
            f"| {'Aer' if backend == 'aer' else 'QuEST'} | {method} | {k} | {len(have)} | "
            f"{g:.2f}× | {min(vs_aer):.2f}–{max(vs_aer):.2f}× | {gmean(vs_own):.2f}× | "
            f"{min(vs_own):.2f}–{max(vs_own):.2f}× | "
            f"{statistics.fmean(data[s][key][0] for s in have):.2f} | "
            f"{statistics.fmean(data[s][key][1] for s in have):.0f} |")

    # head-to-head of the headline configurations, per circuit
    heads = [("aer", "no fusion", "–"), ("aer", "Aer built-in fusion", "–"),
             ("quest", "no fusion", "–"), ("quest", "measured-cost fusion", "–")]
    lines += ["", f"Best on average: **{best[1]}** ({best[0]:.2f}× vs Aer, no fusion).", "",
              "## Per circuit (time in s; noise = control vs no fusion)", "",
              "| seed | gates | Aer no fusion | Aer built-in | QuEST no fusion | QuEST measured-cost | "
              "QuEST measured-cost vs Aer built-in | noise Aer / QuEST |",
              "|---:|---:|---:|---:|---:|---:|---:|---|"]
    for s in seeds:
        d = data[s]
        t = [d.get(h, (None,))[0] for h in heads]
        ratio = f"{t[1] / t[3]:.2f}×" if t[1] and t[3] else "–"
        noise = []
        for b in ("aer", "quest"):
            c, base = d.get((b, "control", "–")), d.get((b, "no fusion", "–"))
            noise.append(f"{(c[0] / base[0] - 1) * 100:+.1f}%" if c and base else "–")
        gates = d[("aer", "no fusion", "–")][1]
        lines.append(f"| {s} | {gates} | " + " | ".join(f"{x:.2f}" if x else "–" for x in t)
                     + f" | {ratio} | {' / '.join(noise)} |")
    text = "\n".join(lines) + "\n"
    if a.out:
        Path(a.out).write_text(text)
        print(f"wrote {a.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
