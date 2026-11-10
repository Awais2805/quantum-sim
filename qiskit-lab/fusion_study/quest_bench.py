#!/usr/bin/env python3
"""Run Qiskit-fused circuits on QuEST (plan B).

For each qubit count n:
  1. build the circuit in a QuEST-friendly gate set (quest_ops.QUEST_BASIS),
  2. make the fusion variants:
       none                         unfused
       horizontal / vertical / both fusion_bench.fuse(), one per --widths k
       diagonal                     merge only exactly-diagonal gates, one per --diag-widths k
       dp / diag+dp                 dp_fusion.fuse_dp() (Python port of Aer's fuser), one per
                                    --dp-costs: 'aer' = Aer's own constants (reproduces Aer's
                                    plan exactly), 'measured' = QuEST-measured cost table
     --cost-model gates horizontal/vertical/both/diagonal with the QuEST-measured table too,
  3. write each variant as a .qops file (quest_ops.write_qops),
  4. for n <= --verify-max-n, run every variant on QuEST from a random product state and
     check the output matches the *unfused* circuit's state (qiskit Statevector, no Aer),
  5. time all variants in one quest_runner call (round-robin reps, gate loop only),
  6. write CSV rows in fusion_bench.py's format (backend=quest), so plot_fusion.py works.

QuEST cost table: measured with quest_runner at --cost-n qubits (time of `copies` copies of
each gate kind / copies), cached as results/cost_table_v2_<host>_quest_t<threads>_n<n>.json.

Build the runner first: ./build_quest.sh
"""

import argparse
import csv
import json
import os
import socket
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import UnitaryGate, get_standard_gate_name_mapping
from qiskit.quantum_info import random_unitary

import fusion_bench as fb
from dp_fusion import fuse_dp
from quest_ops import QUEST_BASIS, read_amps, write_qops
from verify_quest import verify

HERE = Path(__file__).resolve().parent
DEFAULT_RUNNER = HERE / "build" / "quest-linux" / "quest_runner"
GREEDY_MODES = list(fb.FUSION_MODES)  # horizontal, vertical, both
DP_MODES = ["dp", "diag+dp"]
MODES = ["none", *GREEDY_MODES, "diagonal", *DP_MODES]
DEFAULT_MODES = ["none", *GREEDY_MODES, "diagonal", "diag+dp"]
MAX_DENSE_W = 5  # Aer's fuser (and dp_fusion) fuse up to 5 qubits


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--circuit", choices=("qft", "rqc"), default="qft")
    p.add_argument("--depth", type=int, default=0, help="rqc layers (0 = n)")
    p.add_argument("--seed", type=int, default=1234, help="rqc seed; size n uses seed+n")
    p.add_argument("--min-n", type=int, default=4)
    p.add_argument("--max-n", type=int, default=24)
    p.add_argument("--widths", default="2,3,4", help="max fused widths k for horizontal/vertical/both")
    p.add_argument("--diag-widths", default="4,8", help="max widths k for the diagonal mode")
    p.add_argument("--modes", default=",".join(DEFAULT_MODES), help=f"subset of {MODES}")
    p.add_argument("--dp-costs", default="aer,measured", help="cost tables for dp modes: aer, measured")
    p.add_argument("--cost-model", action="store_true",
                   help="only fuse horizontal/vertical/both/diagonal blocks the QuEST table predicts faster")
    p.add_argument("--cost-n", type=int, default=0,
                   help="qubits for QuEST cost calibration (0 = min(max-n, 26, largest that fits in RAM))")
    p.add_argument("--reps", type=int, default=0, help="timed reps per variant (0 = 7 below 20q, else 5)")
    p.add_argument("--threads", type=int, default=0, help="OMP_NUM_THREADS (0 = all logical CPUs)")
    p.add_argument("--control", action="store_true",
                   help="also time the unfused circuit a second time ('control') as a noise check")
    p.add_argument("--verify-max-n", type=int, default=12,
                   help="check every variant's QuEST output against the unfused circuit up to this n")
    p.add_argument("--mem-frac", type=float, default=0.7, help="max statevector size / MemAvailable")
    p.add_argument("--runner", type=Path, default=DEFAULT_RUNNER)
    p.add_argument("--out", type=Path, default=None, help="CSV path (default: results/<circuit>_quest.csv)")
    a = p.parse_args()
    a.widths = [int(x) for x in a.widths.split(",") if x]
    a.diag_widths = [int(x) for x in a.diag_widths.split(",") if x]
    a.modes = [m for m in a.modes.split(",") if m]
    a.dp_costs = [c for c in a.dp_costs.split(",") if c]
    if bad := set(a.modes) - set(MODES):
        p.error(f"unknown modes {bad}")
    if bad := set(a.dp_costs) - {"aer", "measured"}:
        p.error(f"unknown --dp-costs {bad}")
    if a.out is None:
        a.out = HERE / "results" / f"{a.circuit}_quest{'_cost' * a.cost_model}.csv"
    if not a.runner.exists():
        p.error(f"{a.runner} not found; run ./build_quest.sh first")
    return a


def run_runner(runner, args, env):
    proc = subprocess.run([str(runner), *map(str, args)], env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"quest_runner failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.splitlines()


def parse_times(lines, count):
    times = [[] for _ in range(count)]
    for line in lines:
        if line.startswith("RESULT,"):
            _, idx, _, sec = line.split(",")
            times[int(idx)].append(float(sec))
    return times


# --------------------------------------------------------------------------- QuEST cost table

class QuestCosts(fb.CostModel):
    """fusion_bench.CostModel backed by a QuEST-measured table (never measures with Aer)."""

    def __init__(self, table, n_cal):
        self.table, self.n_cal = dict(table), n_cal

    def _measure(self, op):
        raise KeyError(f"no QuEST cost measured for {self.key(op)}; extend the calibration")


def calibration_gates(max_diag_w, rng):
    """CostModel key -> gate instance, for every native in QUEST_BASIS plus fused kinds."""
    mapping = get_standard_gate_name_mapping()
    gates = {}
    for name in QUEST_BASIS:
        cls = mapping[name].base_class
        nparams = len(mapping[name].params)
        gate = cls(*rng.uniform(0.1, 2 * np.pi, nparams))
        gates[f"{name}/{gate.num_qubits}"] = gate
    for w in range(1, MAX_DENSE_W + 1):
        gates[f"dense/{w}"] = UnitaryGate(random_unitary(2**w, seed=w).data, check_input=False)
    for w in range(1, max(MAX_DENSE_W, max_diag_w) + 1):
        phases = np.exp(1j * rng.uniform(0, 2 * np.pi, 2**w))
        gates[f"diag/{w}"] = UnitaryGate(np.diag(phases), check_input=False)
    return gates


def calibrate(runner, env, n_cal, max_diag_w, cache, copies=8, reps=2):
    table = json.loads(cache.read_text()) if cache.exists() else {}
    rng = np.random.default_rng(0)
    gates = calibration_gates(max_diag_w, rng)
    missing = [key for key in gates if key not in table]
    if missing:
        t0 = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="qcal_") as td:
            plans = []
            for i, key in enumerate(missing):
                gate = gates[key]
                qc = QuantumCircuit(n_cal)
                for _ in range(copies):  # random placements average over low/high qubit strides
                    qc.append(gate, rng.choice(n_cal, gate.num_qubits, replace=False).tolist())
                plans.append(Path(td) / f"{i}.qops")
                write_qops(qc, plans[-1])
            times = parse_times(run_runner(runner, ["--reps", reps, "--warmup", 1, *plans], env), len(plans))
        for key, t in zip(missing, times):
            table[key] = min(t) / copies
        cache.write_text(json.dumps(table, indent=1, sort_keys=True))
        print(f"calibrated {len(missing)} gate kinds on QuEST at {n_cal} qubits "
              f"({time.perf_counter() - t0:.1f}s) -> {cache.name}", flush=True)
    return table


# --------------------------------------------------------------------------- variants

def build_variants(base, a, costs):
    """[(mode, k, circuit, transpile_s)] for one base circuit."""
    gate = costs if a.cost_model else None
    variants = []

    def add(mode, k, make):
        t0 = time.perf_counter()
        qc = make()
        variants.append((mode, k, qc, time.perf_counter() - t0))

    if "none" in a.modes:
        variants.append(("none", 0, base, 0.0))
    for k in a.widths:
        for mode in GREEDY_MODES:
            if mode in a.modes:
                add(mode, k, lambda: fb.fuse(base, mode, k, gate))
    if "diagonal" in a.modes:
        for k in a.diag_widths:
            add("diagonal", k, lambda: fb.fuse(base, "diagonal", k, gate))
    for mode in DP_MODES:
        if mode in a.modes:
            for which in a.dp_costs:
                table = "aer" if which == "aer" else costs.table
                add(f"{mode}:{which}", 0, lambda: fuse_dp(base, mode, table, max_qubit=MAX_DENSE_W))
    if a.control:
        variants.append(("control", 0, base, 0.0))
    return variants


# --------------------------------------------------------------------------- main

def main():
    a = parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    threads = a.threads or os.cpu_count()
    env = {**os.environ, "OMP_NUM_THREADS": str(threads), "OMP_PROC_BIND": "close"}

    costs = None
    if a.cost_model or (set(a.modes) & set(DP_MODES) and "measured" in a.dp_costs):
        n_cal = a.cost_n or min(a.max_n, 26, fb.largest_fitting_n(a.mem_frac))
        cache = a.out.parent / f"cost_table_v2_{socket.gethostname()}_quest_t{threads}_n{n_cal}.json"
        max_diag_w = max(a.diag_widths) if "diagonal" in a.modes else MAX_DENSE_W
        costs = QuestCosts(calibrate(a.runner, env, n_cal, max_diag_w, cache), n_cal)
        for key, sec in sorted(costs.table.items(), key=lambda kv: kv[1]):
            print(f"  {key:>10} {sec * 1e3:9.3f} ms")

    with open(a.out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fb.CSV_FIELDS)
        writer.writeheader()

        for n in range(a.min_n, a.max_n + 1):
            need, avail = 16 * 2**n, fb.mem_available_bytes()
            if need > a.mem_frac * avail:
                print(f"n={n}: statevector {need / 2**30:.2f} GiB > {a.mem_frac:.0%} of "
                      f"available {avail / 2**30:.2f} GiB, stopping", flush=True)
                break

            base = fb.build_circuit(a.circuit, n, a.depth, a.seed, basis=QUEST_BASIS)
            variants = build_variants(base, a, costs)

            with tempfile.TemporaryDirectory(prefix="qops_") as td:
                td = Path(td)
                plans = []
                for i, (_, _, qc, _) in enumerate(variants):
                    plans.append(td / f"{i}.qops")
                    write_qops(qc, plans[-1])

                if n <= a.verify_max_n:
                    prep = fb.random_product_state(n)
                    write_qops(prep, td / "prep.qops")
                    run_runner(a.runner, ["--reps", 0, "--verify", td / "prep.qops", td, *plans], env)
                    for i, (mode, k, _, _) in enumerate(variants):
                        overlap = verify(base, prep, read_amps(td / f"{i}.amps", n))
                        if overlap < 1 - 1e-8:
                            raise SystemExit(f"FAIL: n={n} mode={mode} k={k}: QuEST output differs "
                                             f"from the unfused circuit (overlap {overlap:.10f})")

                reps = a.reps or (7 if n < 20 else 5)
                times = parse_times(
                    run_runner(a.runner, ["--reps", reps, "--warmup", int(n < 20), *plans], env), len(variants))

            row_line = [f"n={n:2d}"]
            for i, (mode, k, qc, transpile_s) in enumerate(variants):
                t = times[i]
                row = {"backend": "quest", "circuit": a.circuit, "device": "CPU", "aer_fusion": 0,
                       "cost_model": int(a.cost_model), "n": n, "mode": mode, "k": k, **fb.circuit_stats(qc),
                       "transpile_s": f"{transpile_s:.6f}",
                       "pred_s": f"{costs.predict(qc):.6f}" if costs else "",
                       "sim_med_s": f"{statistics.median(t):.6f}", "sim_min_s": f"{min(t):.6f}",
                       "sim_max_s": f"{max(t):.6f}", "wall_med_s": f"{statistics.median(t):.6f}",
                       "reps": reps, "threads": threads}
                writer.writerow(row)
                tag = {"horizontal": "H", "vertical": "V", "both": "B", "diagonal": "D",
                       "none": "N", "control": "C"}.get(mode, mode)
                row_line.append(f"{tag}{k or ''}:{min(t):.4g}s/{row['ops']}op")
            fh.flush()
            print("  ".join(row_line), flush=True)

    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
