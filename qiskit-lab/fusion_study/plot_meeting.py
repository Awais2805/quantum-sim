#!/usr/bin/env python3
"""Figures and tables for meeting_run.sh: Aer vs QuEST, with and without gate fusion, at one size.

Writes into the results dir, for each circuit (qft, rqc):
  <circuit>_speedup.png        speedup over Aer with no fusion
  <circuit>_sim_time.png       simulation time in seconds
  <circuit>_gates.png          gates applied, i.e. passes over the statevector
  <circuit>_time_per_gate.png  average time per gate application in ms
and RESULTS.md (the same numbers as tables, the noise check, the machine details).
Each PNG has one panel per max fused width k. Bars that do not depend on k (no fusion,
Aer built-in fusion, measured-cost fusion) repeat in every panel.

    python plot_meeting.py results/meeting_n24
"""

import argparse
import csv
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import to_rgb  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
# Fixed categorical slots (validated in this bar order: yellow, blue, orange, aqua); baseline is neutral grey.
COLOR = {"none": "#8f8e88", "aer": "#eda100", "horizontal": "#2a78d6", "vertical": "#eb6834",
         "dp:measured": "#1baf7a"}
STAT = "sim_min_s"
CIRCUITS = {"qft": "QFT", "rqc": "Random circuit"}
SIM_NAME = {"Aer": "Qiskit Aer", "QuEST": "QuEST v4.2"}
SUFFIXES = ("aer_greedy", "aer_cost", "quest_greedy", "quest_cost")

# Bar order within a panel: (simulator, csv suffix, mode, label, depends on k?)
ENTRIES = [
    ("Aer", "aer_greedy", "none", "no fusion", False),
    ("Aer", "aer_greedy", "aer", "Aer built-in fusion", False),
    ("Aer", "aer_greedy", "horizontal", "horizontal, greedy", True),
    ("Aer", "aer_cost", "horizontal", "horizontal, cost model", True),
    ("Aer", "aer_greedy", "vertical", "vertical, greedy", True),
    ("Aer", "aer_cost", "vertical", "vertical, cost model", True),
    ("QuEST", "quest_greedy", "none", "no fusion", False),
    ("QuEST", "quest_greedy", "horizontal", "horizontal, greedy", True),
    ("QuEST", "quest_cost", "horizontal", "horizontal, cost model", True),
    ("QuEST", "quest_greedy", "vertical", "vertical, greedy", True),
    ("QuEST", "quest_cost", "vertical", "vertical, cost model", True),
    ("QuEST", "quest_greedy", "dp:measured", "measured-cost fusion", False),
]
METRICS = [  # (key, file suffix, x label, title, value format, reference line, best is)
    ("speedup", "speedup", "Speedup vs Aer, no fusion (×)", "speedup over Aer with no fusion",
     lambda v: f"{v:.2f}×", 1.0, max),
    ("t", "sim_time", "Simulation time (s)", "simulation time",
     lambda v: f"{v:.1f} s" if v >= 10 else f"{v:.2f} s", None, min),
    ("ops", "gates", "Gates applied", "gates applied", lambda v: f"{v:,.0f}", None, None),
    ("ms_gate", "time_per_gate", "Time per gate (ms)", "time per gate application",
     lambda v: f"{v:.1f} ms", None, None),
]


def tint(color, frac=0.45):
    c, s = to_rgb(color), to_rgb(SURFACE)
    return tuple(si + (ci - si) * frac for ci, si in zip(c, s))


def load_circuit(d, c):
    """Records per k, the widths run, and the noise check, for one circuit."""
    rows = {}
    for suffix in SUFFIXES:
        path = d / f"{c}_{suffix}.csv"
        if path.exists():
            for r in csv.DictReader(open(path)):
                rows[(suffix, r["mode"], int(r["k"]))] = r
    if not rows:
        return None
    jpath = d / f"{c}_aer_fused_ops.json"
    aer_ops = json.loads(jpath.read_text())["fused_ops"] if jpath.exists() else None
    ks = sorted({k for (_, m, k) in rows if m in ("horizontal", "vertical")})

    def rec(sim, suffix, mode, label, k):
        r = rows.get((suffix, mode, k))
        if r is None:
            return None
        ops = aer_ops if mode == "aer" else int(r["ops"])
        return {"sim": sim, "mode": mode, "label": label, "cost": suffix.endswith("cost"), "k": k,
                "t": float(r[STAT]), "ops": ops, "reps": int(r["reps"]), "n": int(r["n"])}

    by_k = {}
    for k in ks:
        recs = [x for sim, suffix, mode, label, dep in ENTRIES
                if (x := rec(sim, suffix, mode, label, k if dep else 0))]
        by_k[k] = recs
    base = {}
    for recs in by_k.values():
        for x in recs:
            if x["mode"] == "none":
                base[x["sim"]] = x["t"]
    for recs in by_k.values():
        for x in recs:
            x["speedup"] = base["Aer"] / x["t"] if "Aer" in base else None
            x["speedup_own"] = base[x["sim"]] / x["t"] if x["sim"] in base else None
            x["ms_gate"] = 1e3 * x["t"] / x["ops"] if x["ops"] else None
    controls = {}
    for sim, suffix in (("Aer", "aer_greedy"), ("QuEST", "quest_greedy")):
        ctl, none = rows.get((suffix, "control", 0)), rows.get((suffix, "none", 0))
        if ctl and none:
            controls[sim] = float(ctl[STAT]) / float(none[STAT]) - 1
    return {"by_k": by_k, "ks": ks, "controls": controls}


def positions(recs):
    """y slots top to bottom, with a header slot before each simulator's group."""
    ys, heads, y, last = [], [], 0.0, None
    for x in recs:
        if x["sim"] != last:
            if last is not None:
                y += 0.6
            heads.append((y, SIM_NAME[x["sim"]]))
            y += 1
            last = x["sim"]
        ys.append(y)
        y += 1
    return ys, heads


def plot(c, data, metric, out, sub):
    key, _, xlabel, title, fmt, ref, best = metric
    plt.rcParams.update({"font.size": 11, "text.color": INK, "axes.labelcolor": INK2,
                         "xtick.color": INK2, "ytick.color": INK2, "hatch.linewidth": 1.2})
    ks = data["ks"]
    fig, axes = plt.subplots(1, len(ks), figsize=(4.9 * len(ks) + 2.4, 6.6), facecolor=SURFACE,
                             sharex=True, squeeze=False)
    axes = axes[0]
    vmax = max(x[key] for recs in data["by_k"].values() for x in recs if x[key] is not None)
    for j, (ax, k) in enumerate(zip(axes, ks)):
        recs = [x for x in data["by_k"][k] if x[key] is not None]
        ys, heads = positions(recs)
        vals = [x[key] for x in recs]
        pick = -1  # bold the winner, unless it is within 2% of the runner-up (a tie)
        if best:
            order = sorted(range(len(vals)), key=lambda i: vals[i], reverse=best is max)
            lead, second = vals[order[0]], vals[order[1]]
            if abs(lead - second) > 0.02 * max(lead, second):
                pick = order[0]
        for i, (x, y) in enumerate(zip(recs, ys)):
            col = COLOR[x["mode"]]
            ax.barh(y, x[key], height=0.72, color=tint(col) if x["cost"] else col,
                    edgecolor=col, linewidth=0, hatch="///" if x["cost"] else None, zorder=2)
            ax.annotate(fmt(x[key]), (x[key], y), xytext=(4, 0), textcoords="offset points",
                        va="center", fontsize=9.5, color=INK if i == pick else INK2,
                        fontweight="bold" if i == pick else "normal", zorder=4,
                        bbox=dict(facecolor=SURFACE, edgecolor="none", pad=0.6))
        ax.set_yticks(ys + [h[0] for h in heads], [x["label"] for x in recs] + [h[1] for h in heads])
        for lab in ax.get_yticklabels()[len(recs):]:
            lab.set_fontweight("bold")
            lab.set_color(INK)
        if j:
            ax.tick_params(labelleft=False)
        ax.invert_yaxis()
        ax.set_xlim(0, vmax * 1.25)
        if ref is not None:
            ax.axvline(ref, color=INK2, linewidth=1, zorder=1)
        ax.set_facecolor(SURFACE)
        ax.grid(True, axis="x", color=GRID, linewidth=1, zorder=0)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0)
        ax.set_title(f"max fused width k = {k}", fontsize=12, pad=8, color=INK)
        ax.set_xlabel(xlabel)
    handles = [Patch(color=COLOR["none"], label="no fusion"),
               Patch(color=COLOR["aer"], label="Aer built-in fusion"),
               Patch(color=COLOR["horizontal"], label="horizontal (Qiskit)"),
               Patch(color=COLOR["vertical"], label="vertical (Qiskit)"),
               Patch(color=COLOR["dp:measured"], label="measured-cost fusion (ours)"),
               Patch(facecolor=tint(INK2), edgecolor=INK2, hatch="///", linewidth=0,
                     label="cost model")]
    fig.legend(handles=handles, loc="upper center", ncol=6 if len(ks) > 2 else 3, frameon=False,
               bbox_to_anchor=(0.5, 0.935), labelcolor=INK, fontsize=10)
    fig.suptitle(f"{CIRCUITS[c]}: {title}", y=1.0, fontsize=14, color=INK)
    fig.text(0.5, 0.955, sub, ha="center", fontsize=10, color=INK2)
    fig.tight_layout(rect=(0, 0, 1, 0.9 if len(ks) > 2 else 0.87))
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print(f"wrote {out}")


def machine(d):
    env = (d / "ENV.txt").read_text() if (d / "ENV.txt").exists() else ""
    lines = env.splitlines()
    cpu = next((ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("Model name")), "?")
    thr = next((ln.split()[1] for ln in lines if ln.startswith("threads:")), "?")
    host = next((ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("host:")), "?")
    return host, cpu, thr, env


def write_md(d, data):
    host, cpu, thr, env = machine(d)
    first = next(iter(data.values()))
    n = first["by_k"][first["ks"][0]][0]["n"]
    L = [f"# Gate fusion on Aer vs QuEST, {n} qubits", "",
         f"Machine: `{host}` ({cpu}), {thr} threads. Max fused width k = {', '.join(map(str, first['ks']))}. "
         f"Time = best of the timed runs (`{STAT}`); only the simulation is timed, not the fusion pass.",
         "Speedups are against **Aer with no fusion** unless the column says otherwise. "
         "Rows with k = – choose their own block sizes.", ""]
    for c, cd in data.items():
        recs0 = cd["by_k"][cd["ks"][0]]
        L += [f"## {CIRCUITS[c]} ({n} qubits, {recs0[0]['reps']} timed run(s) per row)", "",
              "| simulator | method | k | gates applied | time (s) | speedup vs Aer, no fusion "
              "| speedup vs same simulator, no fusion | ms per gate |",
              "|---|---|---:|---:|---:|---:|---:|---:|"]
        seen = set()
        rows = []
        for k in cd["ks"]:
            for x in cd["by_k"][k]:
                ident = (x["sim"], x["mode"], x["cost"], x["k"])
                if ident not in seen:
                    seen.add(ident)
                    rows.append(x)
        order = {(s, lab): i for i, (s, _, _, lab, _) in enumerate(ENTRIES)}
        rows.sort(key=lambda x: (x["sim"] != "Aer", x["k"] > 0, x["k"], order[(x["sim"], x["label"])]))
        for x in rows:
            ms = f"{x['ms_gate']:.2f}" if x["ms_gate"] else "?"
            L.append(f"| {x['sim']} | {x['label']} | {x['k'] or '–'} | {x['ops'] or '?'} | {x['t']:.3f} | "
                     f"{x['speedup']:.2f}× | {x['speedup_own']:.2f}× | {ms} |")
        if cd["controls"]:
            L += ["", "Noise check (the unfused circuit timed twice): " + ", ".join(
                f"{s} {v:+.1%}" for s, v in cd["controls"].items())]
        L.append("")
    L += ["## Reproduce", "", "```",
          f"cd fusion_study && tmux new -d -s meeting 'N={n} bash meeting_run.sh'",
          f"python plot_meeting.py results/{d.name}", "```", "",
          "## Environment (ENV.txt)", "", "```", env.strip(), "```", ""]
    (d / "RESULTS.md").write_text("\n".join(L))
    print(f"wrote {d / 'RESULTS.md'}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dir", type=Path)
    a = p.parse_args()
    data = {c: got for c in CIRCUITS if (got := load_circuit(a.dir, c))}
    if not data:
        raise SystemExit(f"no meeting CSVs in {a.dir}")
    host, cpu, thr, _ = machine(a.dir)
    for c, cd in data.items():
        recs = cd["by_k"][cd["ks"][0]]
        n, reps = recs[0]["n"], recs[0]["reps"]
        gates = next(x["ops"] for x in recs if x["mode"] == "none")
        cpu_short = re.sub(r"\s*(\d+-Core\s*)?Processor", "", cpu)
        sub = (f"{n} qubits · {gates:,} gates · {cpu_short}, {thr} threads · "
               f"best of {reps} run{'s' if reps > 1 else ''}")
        for metric in METRICS:
            plot(c, cd, metric, a.dir / f"{c}_{metric[1]}.png", sub)
    write_md(a.dir, data)
    print((a.dir / "RESULTS.md").read_text())


if __name__ == "__main__":
    main()
