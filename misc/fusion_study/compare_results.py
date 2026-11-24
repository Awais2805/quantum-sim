#!/usr/bin/env python3
"""Merge fusion benchmark CSVs (fusion_bench.py / quest_bench.py, columns = CSV_FIELDS) into
markdown comparison tables. Read-only on the results.

    python compare_results.py results/overnight_vm                # print to stdout
    python compare_results.py results/overnight_vm --out results/overnight_vm/COMPARE.md

Inputs are CSV files or directories (every *.csv inside). The statistic is sim_min_s (fastest
rep). Rows are grouped into runs by (backend, circuit, threads, cost_model, aer_fusion, seed);
the seed is not a CSV column, so it is taken from a 'seed<digits>' part of the file name.

Sections
  1. speedup vs 'none' for every mode, per circuit/backend/n, and the best mode per n
  2. strategies: greedy best-k vs diagonal vs Aer's fuser port vs measured-cost DP
  3. QuEST vs Aer on the same circuit and n: absolute times, unfused and best fused
  4. greedy modes gated by the cost model vs plain greedy
  5. thread scaling (1 thread vs the main thread count) at a fixed n
  6. spread across random-circuit seeds
Noisy sizes (identical-circuit control differs from 'none' by > 15%, the plot_fusion.py rule)
are marked with '!' after n and listed per run.
"""
import argparse
import csv
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

NOISE_TOL = 0.15                      # same threshold as plot_fusion.noisy_sizes
GREEDY = ("horizontal", "vertical", "both")
DP_MODES = ("dp:aer", "dp:measured", "diag+dp:aer", "diag+dp:measured")
NOT_FUSED = ("none", "control")


# --------------------------------------------------------------------------- loading

def load(paths):
    files = []
    for p in map(Path, paths):
        files += sorted(p.glob("*.csv")) if p.is_dir() else [p]
    rows = []
    for f in files:
        seed = re.search(r"seed(\d+)", f.stem)
        with open(f, newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    rows.append({
                        "file": f.name,
                        "backend": r.get("backend") or "aer",
                        "circuit": r.get("circuit") or ("rqc" if "rqc" in f.stem else "qft"),
                        "threads": int(r.get("threads") or 0),
                        "cost_model": int(r.get("cost_model") or 0),
                        "aer_fusion": int(r.get("aer_fusion") or 0),
                        "seed": int(seed.group(1)) if seed else None,
                        "n": int(r["n"]),
                        "mode": r["mode"],
                        "k": int(r["k"]),
                        "ops": int(r["ops"]),
                        "t": float(r["sim_min_s"]),
                    })
                except (KeyError, ValueError) as e:
                    print(f"skipping a row of {f.name}: {e!r}", file=sys.stderr)
    return files, rows


class Run:
    """One group of comparable rows: times[n][label] and ops[n][label]."""

    def __init__(self, key):
        self.key = key
        self.times = defaultdict(dict)
        self.ops = defaultdict(dict)
        self.files = set()
        self.dups = 0

    backend = property(lambda s: s.key[0])
    circuit = property(lambda s: s.key[1])
    threads = property(lambda s: s.key[2])
    cost_model = property(lambda s: s.key[3])
    aer_fusion = property(lambda s: s.key[4])
    seed = property(lambda s: s.key[5])

    def add(self, r):
        lab = label(r["mode"], r["k"])
        if lab in self.times[r["n"]]:
            self.dups += 1  # the same config twice (e.g. a resumed step): keep the faster
            if r["t"] >= self.times[r["n"]][lab]:
                return
        self.times[r["n"]][lab] = r["t"]
        self.ops[r["n"]][lab] = r["ops"]
        self.files.add(r["file"])

    def ns(self):
        return sorted(self.times)

    def speedup(self, n, lab):
        d = self.times.get(n, {})
        return d["none"] / d[lab] if "none" in d and lab in d and d[lab] > 0 else None

    def labels(self):
        seen = {lab for d in self.times.values() for lab in d}
        return sorted(seen, key=label_order)

    def noisy(self):
        """plot_fusion.noisy_sizes: the 'control' run, else vertical k=2 that fused nothing."""
        out, checked = [], 0
        for n, d in self.times.items():
            if "none" not in d:
                continue
            for c in ("control", "vertical k=2"):
                if c in d and self.ops[n][c] == self.ops[n]["none"]:
                    checked += 1
                    if abs(d[c] / d["none"] - 1) > NOISE_TOL:
                        out.append(n)
                    break
        return sorted(out), checked > 0

    def name(self):
        bits = [f"{self.backend}", self.circuit, f"{self.threads}t"]
        if self.cost_model:
            bits.append("cost-model")
        if self.aer_fusion:
            bits.append("aer-fusion-on")
        if self.seed is not None:
            bits.append(f"seed {self.seed}")
        return " / ".join(bits)


def label(mode, k):
    return f"{mode} k={k}" if k > 0 else mode


def label_order(lab):
    mode, _, k = lab.partition(" k=")
    order = ["none", "control", "horizontal", "vertical", "both", "diagonal", *DP_MODES, "aer"]
    return (order.index(mode) if mode in order else len(order), int(k or 0), lab)


def group(rows):
    runs = {}
    for r in rows:
        key = (r["backend"], r["circuit"], r["threads"], r["cost_model"], r["aer_fusion"], r["seed"])
        runs.setdefault(key, Run(key)).add(r)
    return runs


def main_threads(runs):
    """Most common thread count per (backend, circuit) among plain runs: the 'main' setting."""
    c = defaultdict(Counter)
    for run in runs.values():
        if not run.cost_model and run.seed is None:
            c[(run.backend, run.circuit)][run.threads] += sum(len(d) for d in run.times.values())
    return {bc: cnt.most_common(1)[0][0] for bc, cnt in c.items()}


def main_runs(runs):
    mt = main_threads(runs)
    return [r for r in runs.values() if not r.cost_model and r.seed is None and not r.aer_fusion
            and r.threads == mt.get((r.backend, r.circuit))]


# --------------------------------------------------------------------------- formatting

def fx(x):
    return "–" if x is None else f"{x:.2f}×"


def fs(t):
    if t is None:
        return "–"
    return f"{t * 1e3:.1f} ms" if t < 1 else f"{t:.2f} s"


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def ncol(run, n, noisy):
    return f"{n}!" if n in noisy else str(n)


def fused_labels(run, n, include_aer=False):
    return [lab for lab in run.times[n]
            if lab not in NOT_FUSED and (include_aer or lab != "aer")]


def best(run, n, pred=lambda lab: True):
    cand = [lab for lab in fused_labels(run, n) if pred(lab)]
    if not cand:
        return None, None
    lab = min(cand, key=lambda x: run.times[n][x])
    return lab, run.times[n][lab]


# --------------------------------------------------------------------------- sections

def sec_speedups(runs):
    out = ["## 1. Speedup vs unfused, every mode",
           "Speedup = sim_min(none) / sim_min(mode). **Bold** = best of our modes at that n. "
           "`aer` = Aer's built-in fusion (reference, excluded from 'best'). n! = noisy size."]
    for run in sorted(main_runs(runs), key=lambda r: (r.circuit, r.backend)):
        ns = run.ns()
        noisy, has_ctrl = run.noisy()
        bests = {n: best(run, n)[0] for n in ns}
        rows = [["none (time)", *[fs(run.times[n].get("none")) for n in ns]]]
        for lab in run.labels():
            if lab in NOT_FUSED:
                continue
            cells = []
            for n in ns:
                s = fx(run.speedup(n, lab))
                cells.append(f"**{s}**" if bests[n] == lab else s)
            rows.append([lab, *cells])
        rows.append(["best", *[bests[n] or "–" for n in ns]])
        out += [f"\n### {run.name()}",
                table(["mode \\ n", *[ncol(run, n, noisy) for n in ns]], rows),
                note_noise(noisy, has_ctrl)]
    return out


def note_noise(noisy, has_ctrl):
    if not has_ctrl:
        return "_No identical-circuit control in this run, so noise is unchecked._"
    return (f"_Noisy sizes (control vs none > {NOISE_TOL:.0%}): {', '.join(map(str, noisy))}._"
            if noisy else f"_No noisy sizes (control within {NOISE_TOL:.0%} of none)._")


def sec_strategies(runs):
    out = ["## 2. Strategies: greedy best-k vs diagonal vs Aer's fuser vs measured-cost DP",
           "Each cell: speedup vs none (config). Greedy best-k = fastest of horizontal/vertical/both "
           "over all k; diagonal = fastest diagonal width."]
    for run in sorted(main_runs(runs), key=lambda r: (r.circuit, r.backend)):
        ns = run.ns()
        noisy, _ = run.noisy()
        rows = []
        for n in ns:
            g, gt = best(run, n, lambda lab: lab.split(" k=")[0] in GREEDY)
            d, dt = best(run, n, lambda lab: lab.startswith("diagonal"))
            cells = [ncol(run, n, noisy), fs(run.times[n].get("none")),
                     f"{fx(run.speedup(n, g))} ({g})" if g else "–",
                     f"{fx(run.speedup(n, d))} ({d.split('=')[-1] if d else ''})" if d else "–"]
            cells += [fx(run.speedup(n, m)) for m in DP_MODES]
            cells.append(fx(run.speedup(n, "aer")))
            rows.append(cells)
        if not any(any(c != "–" for c in r[3:]) for r in rows):
            continue
        out += [f"\n### {run.name()}",
                table(["n", "none", "greedy best-k", "diagonal (k)", *DP_MODES, "aer built-in"], rows)]
    return out


def sec_backends(runs):
    out = ["## 3. QuEST vs Aer on the same circuit",
           "Absolute sim_min times. 'best fused' = fastest of our modes on that backend. "
           "Ratio = Aer time / QuEST time (> 1: QuEST faster). 'same circuit' compares the unfused "
           "op counts (rqc must use the same gate set on both backends)."]
    mains = main_runs(runs)
    by = {(r.backend, r.circuit): r for r in mains}
    found = False
    for circ in sorted({r.circuit for r in mains}):
        q, a = by.get(("quest", circ)), by.get(("aer", circ))
        if not (q and a):
            continue
        rows = []
        for n in sorted(set(q.ns()) & set(a.ns())):
            qn, an = q.times[n].get("none"), a.times[n].get("none")
            qb, qbt = best(q, n)
            ab, abt = best(a, n)
            aer_t = a.times[n].get("aer")
            same = q.ops[n].get("none") == a.ops[n].get("none")
            rows.append([n, "yes" if same else f"NO ({q.ops[n].get('none')} vs {a.ops[n].get('none')})",
                         fs(qn), fs(an), fx(an / qn if qn and an else None),
                         f"{fs(qbt)} ({qb})" if qb else "–", f"{fs(abt)} ({ab})" if ab else "–",
                         fs(aer_t), fx(abt / qbt if abt and qbt else None),
                         fx(min(x for x in (abt, aer_t, an) if x) / qbt if qbt and an else None)])
        if rows:
            found = True
            out += [f"\n### {circ}: quest {q.threads}t vs aer {a.threads}t",
                    table(["n", "same circuit", "QuEST none", "Aer none", "none: Aer/QuEST",
                           "QuEST best fused", "Aer best fused (ours)", "Aer built-in fusion",
                           "best: Aer/QuEST", "Aer's best anything / QuEST best"], rows)]
    if not found:
        out.append("\n_No circuit has both quest and aer runs yet._")
    return out


def sec_cost_model(runs):
    out = ["## 4. Cost-model-gated greedy vs plain greedy",
           "Speedups vs each run's own 'none'. Best greedy = fastest horizontal/vertical/both/diagonal."]
    mains = {(r.backend, r.circuit): r for r in main_runs(runs)}
    found = False
    for cm in sorted((r for r in runs.values() if r.cost_model), key=lambda r: (r.circuit, r.backend)):
        plain = mains.get((cm.backend, cm.circuit))
        if not plain:
            continue
        greedy = lambda lab: lab.split(" k=")[0] in (*GREEDY, "diagonal")
        rows = []
        for n in sorted(set(cm.ns()) & set(plain.ns())):
            pb, _ = best(plain, n, greedy)
            cb, _ = best(cm, n, greedy)
            row = [n, f"{fx(plain.speedup(n, pb))} ({pb})" if pb else "–",
                   f"{fx(cm.speedup(n, cb))} ({cb})" if cb else "–"]
            for lab in ("horizontal k=4", "both k=4", "diagonal k=8"):
                row.append(f"{fx(plain.speedup(n, lab))} → {fx(cm.speedup(n, lab))}")
            rows.append(row)
        if rows:
            found = True
            out += [f"\n### {cm.name()} vs plain",
                    table(["n", "plain best greedy", "cost-model best greedy",
                           "H4 plain → cost", "B4 plain → cost", "diag8 plain → cost"], rows)]
    if not found:
        out.append("\n_No cost-model runs with a matching plain run yet._")
    return out


def sec_threads(runs):
    out = ["## 5. Thread scaling",
           "Same circuit and n at 1 thread vs the main thread count. Scaling = t(1 thread) / t(main)."]
    mt = main_threads(runs)
    found = False
    for one in sorted((r for r in runs.values() if r.threads == 1 and not r.cost_model and r.seed is None),
                      key=lambda r: (r.circuit, r.backend)):
        m = mt.get((one.backend, one.circuit))
        main = next((r for r in main_runs(runs) if (r.backend, r.circuit) == (one.backend, one.circuit)), None)
        if not main or m == 1:
            continue
        for n in sorted(set(one.ns()) & set(main.ns())):
            rows = []
            for lab in sorted(set(one.times[n]) & set(main.times[n]), key=label_order):
                if lab == "control":
                    continue
                t1, tm = one.times[n][lab], main.times[n][lab]
                rows.append([lab, fs(t1), fs(tm), fx(t1 / tm), fx(one.speedup(n, lab)),
                             fx(main.speedup(n, lab))])
            if rows:
                found = True
                out += [f"\n### {one.backend} / {one.circuit} / n={n}: 1 thread vs {m} threads",
                        table(["mode", "1 thread", f"{m} threads", "scaling",
                               "speedup vs none (1t)", f"speedup vs none ({m}t)"], rows)]
    if not found:
        out.append("\n_No 1-thread runs with a matching main run yet._")
    return out


def sec_seeds(runs):
    out = ["## 6. Random-circuit seed spread",
           "Speedup vs none per seed (seed = the --seed of the run; 'main' = the run without one). "
           "Spread = max / min speedup across seeds."]
    found = False
    seeded = defaultdict(list)
    for r in runs.values():
        if r.seed is not None and not r.cost_model:
            seeded[(r.backend, r.circuit, r.threads)].append(r)
    for (backend, circ, thr), group_ in sorted(seeded.items()):
        main = next((r for r in main_runs(runs)
                     if (r.backend, r.circuit, r.threads) == (backend, circ, thr)), None)
        members = sorted(group_, key=lambda r: r.seed) + ([main] if main else [])
        for n in sorted({n for r in group_ for n in r.ns()}):
            cols = [r for r in members if n in r.times]
            names = [f"seed {r.seed}" if r.seed is not None else "main run" for r in cols]
            labs = sorted({lab for r in cols for lab in r.times[n] if lab not in NOT_FUSED}, key=label_order)
            rows = [["none (time)", *[fs(r.times[n].get("none")) for r in cols], "", ""]]
            for lab in labs:
                s = [r.speedup(n, lab) for r in cols]
                v = [x for x in s if x]
                rows.append([lab, *map(fx, s), fx(statistics.mean(v)) if v else "–",
                             fx(max(v) / min(v)) if len(v) > 1 else "–"])
            rows.append(["best", *[best(r, n)[0] or "–" for r in cols], "", ""])
            found = True
            out += [f"\n### {backend} / {circ} / {thr}t / n={n}",
                    table(["mode", *names, "mean", "spread"], rows)]
    if not found:
        out.append("\n_No seeded runs yet._")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="CSV files or directories of CSVs")
    ap.add_argument("--out", help="write markdown here instead of stdout")
    a = ap.parse_args()

    files, rows = load(a.inputs)
    if not rows:
        sys.exit("no rows found in " + ", ".join(a.inputs))
    runs = group(rows)
    head = ["# Fusion benchmark comparison", "",
            f"Sources: {len(files)} CSV files, {len(rows)} rows, {len(runs)} runs "
            f"(statistic: sim_min_s). Inputs: {', '.join(a.inputs)}.", ""]
    head.append(table(["run", "n range", "configs", "files", "duplicates"],
                      [[r.name(), f"{r.ns()[0]}–{r.ns()[-1]}", len(r.labels()),
                        ", ".join(sorted(r.files)), r.dups]
                       for r in sorted(runs.values(), key=lambda r: r.name())]))
    body = []
    for sec in (sec_speedups, sec_strategies, sec_backends, sec_cost_model, sec_threads, sec_seeds):
        body += ["", *sec(runs)]
    text = "\n".join(head + body) + "\n"
    if a.out:
        Path(a.out).write_text(text)
        print(f"wrote {a.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
