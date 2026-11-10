#!/usr/bin/env python3
"""Gate-fusion study: how Qiskit transpiler-level fusion affects Aer statevector runtime.

Circuits (--circuit):
  qft   Qiskit's synth_qft_full(n): h, cp, swap. Mostly cheap, sparse, diagonal cp gates.
  rqc   Qiskit's random_circuit(n, depth, max_operands=2, seed=seed+n): random 1q/2q gates
        from Qiskit's standard library, mostly dense. The few gates Aer lacks (iswap, ch,
        xx_minus_yy, ...) are translated to Aer's native set; everything else is kept as is.

Fusion modes (circuit-diagram convention: wires run left to right, time flows right):
  none        circuit exactly as built
  horizontal  fuse gates linked through shared qubits (sequential chains along wires)
  vertical    fuse independent gates in the same layer on disjoint qubits (tensor products)
  both        fuse anything inside a width-k window

All modes are built on Qiskit's BlockCollector / BlockCollapser (wrapped in the
CollectAndCollapse transpiler pass):
  horizontal  greedy width-k blocks, split_blocks=True -> only qubit-connected merges
  both        greedy width-k blocks, no splitting
  vertical    split_layers=True over the whole circuit gives the global ASAP layers;
              each layer is then first-fit-decreasing packed into groups of <= k qubits.
Each group of >= 2 gates is collapsed into a single dense UnitaryGate.

Cost model (--cost-model): before the sweep, measure on this machine how long Aer takes to
apply each kind of gate (every native gate in the circuit, plus fused diagonal and dense
unitaries of width 1..k), at a size near the top of the sweep. A block is then fused only if
its fused unitary is predicted to be cheaper than the gates it replaces. Widths are tried from
k down to 2, so when a wide block does not pay off, narrower blocks still get a chance. The
table is cached as JSON next to the CSV.

Correctness: every fused circuit is checked for exact unitary equivalence up to
--verify-max-n qubits, and Aer's output state from a random input is compared with the
unfused circuit's up to --verify-sim-max-n qubits.

By default Aer's own fusion is off so only transpiler-level fusion is measured;
--aer-fusion turns it on for every run.
"""

import argparse
import csv
import json
import socket
import statistics
import time
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.circuit import Gate
from qiskit.circuit.library import UnitaryGate
from qiskit.circuit.random import random_circuit
from qiskit.dagcircuit.collect_blocks import BlockCollapser, BlockCollector
from qiskit.quantum_info import Operator, random_unitary
from qiskit.synthesis import synth_qft_full
from qiskit.transpiler import PassManager
from qiskit.transpiler.passes import CollectAndCollapse
from qiskit_aer import AerSimulator  # also registers QuantumCircuit.save_amplitudes
from qiskit_aer.aererror import AerError

FUSION_MODES = ("horizontal", "vertical", "both")
EXTRA_MODES = ("diagonal",)  # accepted by fuse()/--modes but not run by default
ALL_MODES = ["none", *FUSION_MODES]
CSV_FIELDS = [
    "backend", "circuit", "device", "aer_fusion", "cost_model",
    "n", "mode", "k", "ops", "depth", "fused_blocks", "diag_blocks", "max_width",
    "transpile_s", "pred_s", "sim_med_s", "sim_min_s", "sim_max_s", "wall_med_s", "reps", "threads",
]


# --------------------------------------------------------------------------- circuits

def build_circuit(kind, n, depth, seed, sim=None, basis=None):
    """QFT (h, cp, swap) or a seeded random circuit. For rqc, gates the target cannot run are
    rewritten at optimization level 0: pass `basis` (a gate-name list, e.g. quest_ops.QUEST_BASIS)
    or an Aer simulator `sim` whose target is used."""
    if kind == "qft":
        return synth_qft_full(n)  # h, cp, swap
    qc = random_circuit(n, depth or n, max_operands=2, seed=seed + n)
    if basis is not None:
        return transpile(qc, basis_gates=list(basis), optimization_level=0)
    return transpile(qc, sim, optimization_level=0)  # only rewrites gates Aer doesn't support


# --------------------------------------------------------------------------- fusion

def is_gate(node):
    return isinstance(node.op, Gate)


def is_diagonal(op):
    """Exact test, matching Aer: it only uses its cheaper diagonal kernel when every
    off-diagonal entry is exactly 0 (even 1e-16 sends it down the dense path)."""
    m = op.to_matrix()
    return not np.any(m - np.diag(np.diagonal(m)))


def to_unitary(qc):
    return UnitaryGate(Operator(qc), check_input=False)


def pack_layer(layer, k):
    """First-fit-decreasing pack of one layer's (qubit-disjoint) gates into groups of <= k qubits."""
    bins = []  # [qubits_used, nodes]
    for node in sorted(layer, key=lambda nd: -len(nd.qargs)):
        w = len(node.qargs)
        for b in bins:
            if b[0] + w <= k:
                b[0] += w
                b[1].append(node)
                break
        else:
            bins.append([w, [node]])
    return [nodes for _, nodes in bins]


_DIAG_CACHE = {}


def node_is_diagonal(node):
    """Exact diagonal test for a DAG node, cached for standard gates (by name + params)."""
    op = node.op
    if op.name == "unitary":
        return is_diagonal(op)
    try:
        key = (op.name, op.num_qubits, tuple(float(p) for p in op.params))
    except (TypeError, ValueError):
        return False
    if key not in _DIAG_CACHE:
        try:
            _DIAG_CACHE[key] = is_diagonal(op)
        except Exception:  # no matrix available
            _DIAG_CACHE[key] = False
    return _DIAG_CACHE[key]


def collect_blocks(dag, mode, k):
    # Gates wider than k must fail the filter: BlockCollector loops forever on a matching
    # node that can never fit in max_block_width (happens when narrower passes revisit
    # blocks fused at a larger width).
    def fits(node):
        return is_gate(node) and len(node.qargs) <= k

    collector = BlockCollector(dag)
    if mode == "diagonal":
        # only exactly-diagonal gates; any grouping of them stays diagonal (they commute)
        return collector.collect_all_matching_blocks(
            filter_fn=lambda node: fits(node) and node_is_diagonal(node),
            split_blocks=False, split_layers=False, min_block_size=2, max_block_width=k,
        )
    if mode == "vertical":
        layers = collector.collect_all_matching_blocks(
            filter_fn=fits, split_blocks=False, split_layers=True,
            min_block_size=1, max_block_width=None,
        )
        return [g for layer in layers for g in pack_layer(layer, k) if len(g) >= 2]
    return collector.collect_all_matching_blocks(
        filter_fn=fits,
        split_blocks=(mode == "horizontal"),
        split_layers=False,
        min_block_size=2,
        max_block_width=k,
    )


def block_circuit(dag, block):
    qubits = sorted({q for nd in block for q in nd.qargs}, key=lambda q: dag.find_bit(q).index)
    pos = {q: i for i, q in enumerate(qubits)}
    qc = QuantumCircuit(len(qubits))
    for nd in block:
        qc.append(nd.op, [pos[q] for q in nd.qargs])
    return qc


def fusion_pass_manager(mode, k, costs=None):
    def collect(dag):
        blocks = collect_blocks(dag, mode, k)
        if costs is not None:
            blocks = [b for b in blocks if costs.profitable(b, block_circuit(dag, b))]
        return blocks

    def collapse(dag, blocks):
        return BlockCollapser(dag).collapse_to_operation(blocks, to_unitary)

    return PassManager([CollectAndCollapse(collect, collapse)])


def fuse(qc, mode, k, costs=None):
    if costs is None:
        return fusion_pass_manager(mode, k).run(qc)
    for w in range(k, 1, -1):  # widest first; unprofitable blocks are left for narrower widths
        qc = fusion_pass_manager(mode, w, costs).run(qc)
    return qc


# --------------------------------------------------------------------------- cost model

class CostModel:
    """Measured seconds per gate application at n_cal qubits, keyed by gate kind.

    Native gates are keyed "name/width" (e.g. "cp/2"); fused unitaries "diag/w" or "dense/w",
    since Aer applies diagonal matrices with a cheaper kernel. Costs are scaled by 2^(n-n_cal)
    to other sizes. That scaling is only approximate: on the 2-vCPU VM, costs measured at 22
    qubits predicted fused gates at 26 qubits within 1% but under-predicted cheap native gates
    by 14-20%, so n_cal should sit near the top of the sweep (see main()).
    """

    def __init__(self, sim, n_cal, cache_path, copies=6, reps=2):
        self.sim, self.n_cal, self.copies, self.reps = sim, n_cal, copies, reps
        self.cache_path = cache_path
        self.table = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        self.rng = np.random.default_rng(0)
        self._base = None

    @staticmethod
    def key(op):
        if op.name == "unitary":
            return f"{'diag' if is_diagonal(op) else 'dense'}/{op.num_qubits}"
        return f"{op.name}/{op.num_qubits}"  # separator: gate "u" on 1 qubit vs gate "u1"

    def op_cost(self, op):
        key = self.key(op)
        if key not in self.table:
            self.table[key] = self._measure(op)
            self.cache_path.write_text(json.dumps(self.table, indent=1, sort_keys=True))
        return self.table[key]

    def prime(self, kmax, circuit):
        """Measure every gate kind the sweep can need, so transpile timings exclude calibration."""
        for w in range(1, kmax + 1):
            self.op_cost(UnitaryGate(random_unitary(2**w, seed=w).data, check_input=False))
            phases = np.exp(1j * self.rng.uniform(0, 2 * np.pi, 2**w))
            self.op_cost(UnitaryGate(np.diag(phases), check_input=False))
        for inst in circuit.data:
            self.op_cost(inst.operation)

    def profitable(self, nodes, qc):
        before = sum(self.op_cost(nd.op) for nd in nodes)
        return self.op_cost(to_unitary(qc)) < before

    def predict(self, qc):
        """Predicted simulation time (s) of qc, scaled from n_cal to qc's size."""
        return sum(self.op_cost(inst.operation) for inst in qc.data) * 2.0 ** (qc.num_qubits - self.n_cal)

    def _time(self, qc):
        qc = qc.copy()
        qc.save_amplitudes([0])
        return min(self.sim.run(qc, shots=1).result().results[0].time_taken for _ in range(self.reps))

    def _prep(self):
        qc = QuantumCircuit(self.n_cal)
        qc.h(range(self.n_cal))  # spread amplitude everywhere
        return qc

    def _measure(self, op):
        if self._base is None:
            self._base = self._time(self._prep())
        qc = self._prep()
        for _ in range(self.copies):  # random placements average over low/high qubit strides
            qc.append(op, self.rng.choice(self.n_cal, op.num_qubits, replace=False).tolist())
        return max((self._time(qc) - self._base) / self.copies, 1e-9)


# --------------------------------------------------------------------------- measurement

def circuit_stats(qc):
    fused = diag = max_width = 0
    for inst in qc.data:
        op = inst.operation
        max_width = max(max_width, op.num_qubits)
        if op.name == "unitary":
            fused += 1
            diag += is_diagonal(op)
    return {
        "ops": len(qc.data),
        "depth": qc.depth(),
        "fused_blocks": fused,
        "diag_blocks": diag,
        "max_width": max_width,
    }


def make_sim(threads, aer_fusion=False, device="CPU"):
    opts = {"method": "statevector", "device": device,
            "enable_truncation": False, "fusion_enable": aer_fusion}
    if aer_fusion:
        opts["fusion_threshold"] = 1  # let Aer fuse at every qubit count
    if threads:
        opts["max_parallel_threads"] = threads
    return AerSimulator(**opts)


def run_once(sim, qc):
    t0 = time.perf_counter()
    res = sim.run(qc, shots=1).result()
    wall = time.perf_counter() - t0
    if not res.success:
        raise RuntimeError(f"Aer run failed: {res.status}")
    exp = res.results[0]
    return exp.time_taken, wall, exp.metadata.get("parallel_state_update", "")


def mem_available_bytes():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return float("inf")


def largest_fitting_n(mem_frac, cap=64):
    budget = mem_frac * mem_available_bytes()
    n = 1
    while n < cap and 16 * 2 ** (n + 1) <= budget:
        n += 1
    return n


def random_product_state(n, seed=7):
    rng = np.random.default_rng(seed)
    qc = QuantumCircuit(n)
    for q in range(n):
        qc.u(*rng.uniform(0, 2 * np.pi, 3), q)
    return qc


def aer_output(sim, prep, qc):
    """Statevector Aer produces for qc applied to the state prepared by prep."""
    c = prep.compose(qc)
    c.save_statevector()
    return np.asarray(sim.run(c).result().get_statevector())


# --------------------------------------------------------------------------- main

def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--circuit", choices=("qft", "rqc"), default="qft")
    p.add_argument("--depth", type=int, default=0, help="rqc layers (0 = n)")
    p.add_argument("--seed", type=int, default=1234, help="rqc seed; size n uses seed+n")
    p.add_argument("--basis", choices=("aer", "quest"), default="aer",
                   help="rqc gate set: 'aer' (rewrite only gates Aer lacks) or 'quest' (quest_ops.QUEST_BASIS, "
                        "the same circuits quest_bench.py runs)")
    p.add_argument("--min-n", type=int, default=4)
    p.add_argument("--max-n", type=int, default=26)
    p.add_argument("--widths", default="2,3,4", help="comma-separated max fused widths k")
    p.add_argument("--modes", default=",".join(ALL_MODES), help=f"subset of {ALL_MODES}")
    p.add_argument("--reps", type=int, default=0, help="timed reps per config (0 = 7 below 20q, else 5)")
    p.add_argument("--threads", type=int, default=0, help="Aer max_parallel_threads (0 = all)")
    p.add_argument("--device", choices=("CPU", "GPU"), default="CPU",
                   help="Aer device; GPU needs the qiskit-aer-gpu package")
    p.add_argument("--aer-fusion", action="store_true",
                   help="turn Aer's built-in fusion ON for every run (default: off)")
    p.add_argument("--aer-fusion-ref", action="store_true",
                   help="add reference series 'aer': unfused circuit with Aer's built-in fusion on")
    p.add_argument("--cost-model", action="store_true",
                   help="only fuse blocks predicted (from measured gate costs) to be faster")
    p.add_argument("--cost-n", type=int, default=0,
                   help="qubits used to measure gate costs (0 = min(max-n, 26, largest size that fits in RAM))")
    p.add_argument("--control", action="store_true",
                   help="also time the unfused circuit a second time ('control') as a noise check")
    p.add_argument("--verify-max-n", type=int, default=8, help="check unitary equivalence up to this n")
    p.add_argument("--verify-sim-max-n", type=int, default=12,
                   help="check Aer's output state of every fused circuit against the unfused one up to this n")
    p.add_argument("--mem-frac", type=float, default=0.7, help="max statevector size / MemAvailable")
    p.add_argument("--out", type=Path, default=None,
                   help="CSV path (default: results/<circuit>_fusion[_aerfusion][_cost][_gpu].csv)")
    a = p.parse_args()
    a.widths = [int(x) for x in a.widths.split(",") if x]
    a.modes = [m for m in a.modes.split(",") if m]
    bad = set(a.modes) - set(ALL_MODES) - set(EXTRA_MODES)
    if bad:
        p.error(f"unknown modes {bad}")
    if a.out is None:
        name = a.circuit + "_fusion" + "_aerfusion" * a.aer_fusion + "_cost" * a.cost_model
        name += "_gpu" * (a.device == "GPU")
        a.out = Path(__file__).resolve().parent / "results" / f"{name}.csv"
    if a.aer_fusion and a.aer_fusion_ref:
        print("--aer-fusion is on, so the 'aer' reference would equal 'none'; skipping it")
        a.aer_fusion_ref = False
    return a


def main():
    a = parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    sim = make_sim(a.threads, a.aer_fusion, a.device)
    raw_sim = make_sim(a.threads, False, a.device)  # Aer fusion off: circuit building + cost model
    aer_sim = make_sim(a.threads, True, a.device) if a.aer_fusion_ref else None
    flags = {"backend": "aer", "circuit": a.circuit, "device": a.device,
             "aer_fusion": int(a.aer_fusion), "cost_model": int(a.cost_model)}

    basis = None
    if a.basis == "quest":
        from quest_ops import QUEST_BASIS
        basis = QUEST_BASIS
    costs = None
    if a.cost_model:
        fit = largest_fitting_n(a.mem_frac) if a.device == "CPU" else a.max_n
        n_cal = a.cost_n or min(a.max_n, 26, fit)
        cache = a.out.parent / f"cost_table_v2_{socket.gethostname()}_{a.device}_t{a.threads or 'all'}_n{n_cal}.json"
        costs = CostModel(raw_sim, n_cal, cache)
        t0 = time.perf_counter()
        costs.prime(max(a.widths), build_circuit(a.circuit, n_cal, a.depth, a.seed, raw_sim, basis))
        print(f"cost model: {len(costs.table)} gate kinds at {n_cal} qubits "
              f"({time.perf_counter() - t0:.1f}s, cached in {cache.name})")
        for key, sec in sorted(costs.table.items(), key=lambda kv: kv[1]):
            print(f"  {key:>14} {sec * 1e3:9.3f} ms")

    with open(a.out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()

        for n in range(a.min_n, a.max_n + 1):
            need, avail = 16 * 2**n, mem_available_bytes()
            if a.device == "CPU" and need > a.mem_frac * avail:
                print(f"n={n}: statevector {need / 2**30:.2f} GiB > {a.mem_frac:.0%} of "
                      f"available {avail / 2**30:.2f} GiB, stopping", flush=True)
                break

            base = build_circuit(a.circuit, n, a.depth, a.seed, raw_sim, basis)
            if costs is not None:
                costs.prime(0, base)  # measure any gate kinds not seen yet (outside transpile timing)
            ref_op = Operator(base) if n <= a.verify_max_n else None
            prep = random_product_state(n)
            ref_sv = aer_output(raw_sim, prep, base) if n <= a.verify_sim_max_n else None

            # config: (mode, k, circuit, transpile_s, simulator)
            configs = []
            if "none" in a.modes:
                configs.append(("none", 0, base, 0.0, sim))
            for k in a.widths:
                for mode in a.modes:
                    if mode == "none":
                        continue
                    t0 = time.perf_counter()
                    fused = fuse(base, mode, k, costs)
                    transpile_s = time.perf_counter() - t0
                    if ref_op is not None and not Operator(fused).equiv(ref_op):
                        raise SystemExit(f"FAIL: n={n} mode={mode} k={k} is not equivalent to the circuit")
                    if ref_sv is not None:
                        overlap = abs(np.vdot(ref_sv, aer_output(raw_sim, prep, fused)))
                        if overlap < 1 - 1e-8:
                            raise SystemExit(f"FAIL: n={n} mode={mode} k={k}: Aer output differs "
                                             f"from the unfused circuit (overlap {overlap:.10f})")
                    configs.append((mode, k, fused, transpile_s, sim))
            if a.control:
                configs.append(("control", 0, base, 0.0, sim))
            if aer_sim is not None:
                configs.append(("aer", 0, base, 0.0, aer_sim))

            runnable = []
            for mode, k, circ, transpile_s, s in configs:
                c = circ.copy()
                c.save_amplitudes([0])  # acts on all qubits, so nothing is truncated
                runnable.append((c, s))

            reps = a.reps or (7 if n < 20 else 5)
            sim_t = [[] for _ in configs]
            wall_t = [[] for _ in configs]
            threads = [""] * len(configs)
            try:
                if n < 20:  # warm-up; at large n a run costs the same as a timed rep
                    for c, s in runnable:
                        run_once(s, c)
                for r in range(reps):
                    # round-robin with a rotating start so drift/throttling spreads evenly
                    for j in range(len(configs)):
                        i = (j + r) % len(configs)
                        c, s = runnable[i]
                        ts, tw, th = run_once(s, c)
                        sim_t[i].append(ts)
                        wall_t[i].append(tw)
                        threads[i] = th
            except (RuntimeError, AerError, MemoryError) as e:
                print(f"n={n}: simulation failed ({e}); stopping", flush=True)
                break

            line = [f"n={n:2d}"]
            for i, (mode, k, circ, transpile_s, _) in enumerate(configs):
                pred = "" if costs is None or mode == "aer" else f"{costs.predict(circ):.6f}"
                row = {**flags, "n": n, "mode": mode, "k": k, **circuit_stats(circ),
                       "transpile_s": f"{transpile_s:.6f}", "pred_s": pred,
                       "sim_med_s": f"{statistics.median(sim_t[i]):.6f}",
                       "sim_min_s": f"{min(sim_t[i]):.6f}",
                       "sim_max_s": f"{max(sim_t[i]):.6f}",
                       "wall_med_s": f"{statistics.median(wall_t[i]):.6f}",
                       "reps": reps, "threads": threads[i]}
                writer.writerow(row)
                tag = mode[0].upper() + (str(k) if k else "")
                line.append(f"{tag}:{min(sim_t[i]):.4g}s/{row['ops']}op")
            fh.flush()
            print("  ".join(line), flush=True)

    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
