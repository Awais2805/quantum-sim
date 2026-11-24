#!/usr/bin/env python3
"""Plot fusion_bench.py results: one PNG per comparison, each with one panel per max fused width k.

  <stem>_runtime.png        simulation time vs n
  <stem>_speedup.png        speedup over no fusion vs n
  <stem>_gates.png          gates applied (= passes over the statevector) vs n
  <stem>_time_per_gate.png  average cost of one gate application vs n

Panels within a PNG share their y-axis so the k sweeps are directly comparable.
Also prints a summary table (the "table view") for the largest n measured.
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

NOISE_TOL = 0.15  # flag n where two identical circuits' times differ by more than this

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
FUSED = ("horizontal", "vertical", "both")
PER_K = (*FUSED, "diagonal")  # modes run once per width k (one panel per k)
# Categorical slots in fixed palette order; baseline/reference are neutral greys.
STYLE = {  # mode -> (legend label, colour, linestyle, end-label tag)
    "none": ("none (baseline)", "#52514e", (0, (5, 2)), None),
    "horizontal": ("horizontal", "#2a78d6", "-", "H"),
    "vertical": ("vertical", "#eb6834", "-", "V"),
    "both": ("both", "#1baf7a", "-", "B"),
    "diagonal": ("diagonal only", "#eda100", (0, (6, 2)), "D"),
    "diag+dp:aer": ("Aer's fuser (diag+dp, Aer costs)", "#e87ba4", "-", "AerF"),
    "diag+dp:measured": ("diag+dp, measured costs", "#008300", "-", "DPm"),
    "dp:aer": ("dp, Aer costs", "#6250d6", (0, (3, 1.5)), "dpA"),
    "dp:measured": ("dp, measured costs", "#e34948", (0, (3, 1.5)), "dpM"),
    "aer": ("Aer built-in fusion (ref)", "#a3a29c", (0, (1, 1.5)), None),
}
ANY_K = tuple(m for m in STYLE if ":" in m)  # width chosen by the algorithm: drawn in every panel
STAT = "sim_min_s"  # min over reps: robust when other processes steal CPU; --stat med to change


def sim(r):
    return float(r[STAT])


def load(path):
    data = defaultdict(dict)  # (mode, k) -> {n: row}
    meta = {}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            data[(r["mode"], int(r["k"]))][int(r["n"])] = r
            meta = meta or r
    return data, meta


def title_parts(meta):
    """(prefix, suffix) for figure titles; older CSVs without these columns were QFT/CPU/off/off."""
    circuit = meta.get("circuit", "qft").upper()
    device = meta.get("device", "CPU")
    fusion = "cost-model fusion" if meta.get("cost_model") == "1" else "greedy fusion"
    if meta.get("backend", "aer") == "quest":
        return f"{circuit} on QuEST statevector ({device})", f"  ({fusion} in Qiskit)"
    aer = "Aer fusion on" if meta.get("aer_fusion") == "1" else "Aer fusion off"
    return f"{circuit} on Qiskit Aer statevector ({device})", f"  ({aer}, {fusion})"


def style_axis(ax, scale):
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0)
    ax.set_yscale(scale)


def add_end_labels(ax, labels):
    """Selective direct labels at line ends; drop any that would collide (legend covers them)."""
    lo, hi = ax.get_ylim()
    last = None
    for x, y, text in sorted(labels, key=lambda t: t[1]):
        if last is None or (y - last) > 0.06 * (hi - lo):
            ax.annotate(text, (x, y), xytext=(5, 0), textcoords="offset points",
                        va="center", fontsize=9, color=INK2)
            last = y


def noisy_sizes(data, base):
    """Sizes where two runs of the identical circuit disagree. Uses the explicit 'control' run
    (fusion_bench.py --control) if present; otherwise any vertical k=2 run that fused nothing
    (true for QFT), since that circuit is identical to the unfused one."""
    ctrl = data.get(("control", 0)) or data.get(("vertical", 2), {})
    noisy = []
    checked = 0
    for n, r in ctrl.items():
        if n in base and r["ops"] == base[n]["ops"]:
            checked += 1
            ratio = sim(r) / sim(base[n])
            if abs(ratio - 1) > NOISE_TOL:
                noisy.append(n)
    if not checked:
        print("note: no identical-circuit control in this CSV, so timing noise is not checked "
              "(rerun fusion_bench.py with --control)")
    return sorted(noisy)


def plot_metric(data, ks, metric, out, titles, noisy=()):
    name, ylabel, fn, scale, with_aer, end_fmt = metric
    plt.rcParams.update({
        "font.size": 11, "axes.labelcolor": INK2, "axes.titlecolor": INK,
        "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
        "lines.solid_capstyle": "round", "lines.dash_capstyle": "round",
    })
    fig, axes = plt.subplots(1, len(ks), sharex=True, sharey=True, squeeze=False,
                             figsize=(5.2 * len(ks), 4.8), facecolor=SURFACE)
    axes = axes[0]
    end_labels = defaultdict(list)
    for ax, k in zip(axes, ks):
        style_axis(ax, scale)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        for n in noisy:
            ax.axvspan(n - 0.5, n + 0.5, color="#ecebe6", zorder=0, linewidth=0)
        series = ([("none", 0)] + [(m, k) for m in PER_K] + [(m, 0) for m in ANY_K]
                  + ([("aer", 0)] if with_aer else []))
        for key in series:
            if key not in data:
                continue
            label, color, ls, tag = STYLE[key[0]]
            pts = [(n, fn(n, r)) for n, r in sorted(data[key].items())]
            pts = [(n, y) for n, y in pts if y is not None]
            if not pts:
                continue
            xs, ys = zip(*pts)
            ax.plot(xs, ys, color=color, linestyle=ls, linewidth=2, label=label)
            if end_fmt and tag:
                end_labels[ax].append((xs[-1], ys[-1], f"{tag} {end_fmt(ys[-1])}"))
        if name == "speedup":
            ax.axhline(1.0, color=INK2, linewidth=1)
        ax.set_title(f"max fused width k = {k}", fontsize=12, pad=8)
        ax.set_xlabel("qubits (n)")
        ax.margins(x=0.14)  # room for end labels
    axes[0].set_ylabel(ylabel)
    for ax, labels in end_labels.items():
        add_end_labels(ax, labels)

    legend = {}  # label -> handle, across panels (diagonal k may exist in only some panels)
    for ax in axes:
        for h, lab in zip(*ax.get_legend_handles_labels()):
            legend.setdefault(lab, h)
    order = [STYLE[m][0] for m in STYLE]
    labels = sorted(legend, key=lambda lab: order.index(lab) if lab in order else len(order))
    handles = [legend[lab] for lab in labels]
    if noisy and name in ("runtime", "speedup", "time_per_gate"):
        handles.append(Patch(color="#ecebe6"))
        labels.append(f"noisy size (identical-circuit control off by >{NOISE_TOL:.0%})")
    else:
        for ax in axes:  # gate counts are exact; no noise shading there
            for patch in list(ax.patches):
                patch.remove()
    fig.legend(handles, labels, loc="upper center", ncol=min(len(labels), 5), frameon=False,
               bbox_to_anchor=(0.5, 0.95), labelcolor=INK)
    fig.suptitle(f"{titles[0]}: {ylabel.lower()}{titles[1]}",
                 y=1.0, fontsize=13, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print(f"wrote {out}")


def main():
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", type=Path, nargs="?", default=here / "results" / "aer_laptop" / "qft_fusion.csv")
    p.add_argument("--out-dir", type=Path, default=None, help="where PNGs go (default: next to the CSV)")
    p.add_argument("--min-n", type=int, default=None, help="hide n below this (tiny-n noise)")
    p.add_argument("--stat", choices=("min", "med"), default="min", help="which Aer time per config")
    a = p.parse_args()
    global STAT
    STAT = f"sim_{a.stat}_s"
    out_dir = a.out_dir or a.csv.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    data, meta = load(a.csv)
    if a.min_n:
        data = {key: {n: r for n, r in rows.items() if n >= a.min_n} for key, rows in data.items()}
    base = data.get(("none", 0), {})
    ks = sorted({k for (m, k) in data if m in PER_K}) or [0]

    # (file suffix, y label, value fn, y scale, include Aer ref?, end-label formatter or None)
    # Aer fuses internally, so its gate count and per-gate cost are not comparable: excluded there.
    metrics = [
        ("runtime", f"Simulation time ({a.stat} of reps, s)", lambda n, r: sim(r), "log", True, None),
        ("speedup", "Speedup vs no fusion (×)",
         lambda n, r: sim(base[n]) / sim(r) if n in base else None, "linear", True,
         lambda y: f"{y:.2f}×"),
        ("gates", "Gates applied (= statevector passes)", lambda n, r: int(r["ops"]), "linear", False,
         lambda y: f"{y:.0f}"),
        ("time_per_gate", "Time per gate application (ms)",
         lambda n, r: 1e3 * sim(r) / int(r["ops"]), "log", False, None),
    ]
    titles = title_parts(meta)
    noisy = noisy_sizes(data, base)
    if noisy:
        print(f"noisy sizes (control mismatch > {NOISE_TOL:.0%}): {noisy}")
    for metric in metrics:
        plot_metric(data, ks, metric, out_dir / f"{a.csv.stem}_{metric[0]}.png", titles, noisy)

    # Table view: largest n with a baseline
    if base:
        n = max(base)
        print(f"\nn = {n} qubits  (none: {sim(base[n]):.3f} s, {base[n]['ops']} gates)")
        print(f"{'k':>2} {'mode':<17} {'gates':>6} {'diag':>5} {'time s':>9} {'speedup':>8} {'ms/gate':>8}")
        keys = [(m, k) for k in ks for m in PER_K] + [(m, 0) for m in ANY_K]
        for m, k in keys:
            r = data.get((m, k), {}).get(n)
            if r:
                print(f"{k or '-':>2} {m:<17} {r['ops']:>6} {r['diag_blocks']:>5} {sim(r):>9.3f} "
                      f"{sim(base[n]) / sim(r):>7.2f}× {1e3 * sim(r) / int(r['ops']):>8.2f}")
        r = data.get(("aer", 0), {}).get(n)
        if r:
            print(f" - {'aer-fusion':<17} {'':>6} {'':>5} {sim(r):>9.3f} {sim(base[n]) / sim(r):>7.2f}×")


if __name__ == "__main__":
    main()
