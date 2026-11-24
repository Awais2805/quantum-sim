"""Cost table for the fusion pass: measured seconds per gate kind on this machine.

Keys are "name/width" for native gates ("h/1", "cp/2") and "dense/w" / "diag/w" for fused
blocks. Every kind is timed on stock QuEST through quest_runner: a circuit of `copies` copies of
the gate on random qubits at n_cal qubits, best of `reps` timed runs, divided by `copies`.

Recalibrate per machine and per memory tier (e.g. under numactl --membind for DRAM vs CXL).
Use an n_cal whose statevector overflows every cache, and one thread per physical core.
"""
import json
import os
import tempfile
import time
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import UnitaryGate, get_standard_gate_name_mapping
from qiskit.quantum_info import random_unitary

from circuits import QUEST_BASIS
from qops import parse_times, run_runner, write_qops

MAX_DENSE_W = 5  # widest dense block the fuser may build (Aer's default fusion_max_qubit)
MAX_DIAG_W = 8   # widest diagonal block (diagonal_blocks)


def calibration_gates(rng, max_dense_w=MAX_DENSE_W, max_diag_w=MAX_DIAG_W):
    """table key -> gate instance: every native in QUEST_BASIS plus fused dense/diag widths."""
    mapping = get_standard_gate_name_mapping()
    gates = {}
    for name in QUEST_BASIS:
        std = mapping[name]
        gate = std.base_class(*rng.uniform(0.1, 2 * np.pi, len(std.params)))
        gates[f"{name}/{gate.num_qubits}"] = gate
    for w in range(1, max_dense_w + 1):
        gates[f"dense/{w}"] = UnitaryGate(random_unitary(2**w, seed=w).data, check_input=False)
    for w in range(1, max_diag_w + 1):
        gates[f"diag/{w}"] = UnitaryGate(np.diag(np.exp(1j * rng.uniform(0, 2 * np.pi, 2**w))),
                                         check_input=False)
    return gates


def measure(n, threads, copies=8, reps=3, seed=0):
    """{kind: seconds per gate} for every kind in calibration_gates, timed on QuEST at n qubits."""
    rng = np.random.default_rng(seed)
    gates = calibration_gates(rng)
    env = {**os.environ, "OMP_NUM_THREADS": str(threads), "OMP_PROC_BIND": "close"}
    with tempfile.TemporaryDirectory(prefix="qcal_") as td:
        plans = []
        for i, gate in enumerate(gates.values()):
            qc = QuantumCircuit(n)
            for _ in range(copies):  # random placements average over low/high qubit strides
                qc.append(gate, rng.choice(n, gate.num_qubits, replace=False).tolist())
            plans.append(Path(td) / f"{i}.qops")
            write_qops(qc, plans[-1])
        times = parse_times(run_runner(["--reps", reps, "--warmup", 1, *plans], env), len(plans))
    return {k: min(t) / copies for k, t in zip(gates, times)}


def calibrate(n_cal, threads, cache):
    """Load the table from `cache` if it exists, otherwise measure it and save it there."""
    cache = Path(cache)
    if cache.exists():
        print(f"cost table: {cache} (delete it to re-measure)", flush=True)
        return load(cache)
    t0 = time.perf_counter()
    table = measure(n_cal, threads)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(table, indent=1, sort_keys=True))
    print(f"measured {len(table)} gate kinds on QuEST at {n_cal} qubits, {threads} threads "
          f"({time.perf_counter() - t0:.1f}s) -> {cache}", flush=True)
    return table


def load(path):
    return json.loads(Path(path).read_text())
