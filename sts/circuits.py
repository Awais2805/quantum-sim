"""Benchmark circuits, in the gate set the QuEST runner accepts.

    qft  Qiskit's synth_qft_full(n): h, cp, swap. Mostly diagonal cp gates.
    rqc  Qiskit's random_circuit(n, depth=n, max_operands=2, seed=seed+n), rewritten into
         QUEST_BASIS at optimization level 0 (only gates outside the basis are touched).

Same builds as the pre-debloat scripts (fusion_bench.build_circuit with basis=QUEST_BASIS),
so circuit fingerprints match results/head_to_head.
"""
import hashlib

import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.circuit.random import random_circuit
from qiskit.synthesis import synth_qft_full

# every gate qops.py can encode; fused blocks are 'unitary' gates on top of these
QUEST_BASIS = ["h", "x", "y", "z", "s", "sdg", "t", "tdg", "sx", "sxdg", "rx", "ry", "rz", "p",
               "u", "cx", "cy", "cz", "cp", "crx", "cry", "crz", "swap"]
KINDS = ("qft", "rqc")


def build(kind, n, seed=1234, depth=0, same_seed=False):
    """same_seed: rqc uses `seed` at every n instead of seed+n."""
    if kind == "qft":
        return synth_qft_full(n)
    if kind == "rqc":
        qc = random_circuit(n, depth or n, max_operands=2, seed=seed if same_seed else seed + n)
        return transpile(qc, basis_gates=QUEST_BASIS, optimization_level=0)
    raise ValueError(f"unknown circuit kind {kind!r}, expected one of {KINDS}")


def random_product_state(n, seed=7):
    """Random single-qubit rotations on every qubit: every amplitude non-zero, cheap to build."""
    rng = np.random.default_rng(seed)
    qc = QuantumCircuit(n)
    for q in range(n):
        qc.u(*rng.uniform(0, 2 * np.pi, 3), q)
    return qc


def fingerprint(qc):
    """Short hash of the gate list, to check two runs used the same circuit."""
    h = hashlib.sha256()
    for inst in qc.data:
        h.update(inst.operation.name.encode())
        h.update(str([qc.find_bit(q).index for q in inst.qubits]).encode())
        h.update(str([round(float(p), 12) for p in inst.operation.params]).encode())
    return h.hexdigest()[:12]
