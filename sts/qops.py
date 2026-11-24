"""Qiskit circuit <-> .qops op file (the plan handed to the runtime), and helpers to run
runtime/quest_runner (a QuEST v4 interpreter: one QuEST API call per op).

.qops v1, little-endian:
  header  "QOPS" | u32 version=1 | u32 n | u32 num_ops
  per op  u8 opcode | u8 k | k x u32 qubits | u8 nparams | nparams x f64 | payload
  payload DENSE: 4^k x (f64 re, f64 im), row-major M[row][col]
          DIAG:  2^k x (f64 re, f64 im)
          other ops: none

Conventions (Qiskit's, passed through unchanged):
  - qubits in qargs order; controlled gates are [control, target]; CP is [a, b]
  - DENSE/DIAG: qubits[0] is the least significant bit of the matrix index
  - angles in radians: rz(t) = diag(e^{-it/2}, e^{it/2}), p(l) = diag(1, e^{il})

Gate mapping: sdg/tdg -> PHASE(-pi/2 / -pi/4); u, sx, sxdg -> DENSE k=1; a fused 'unitary'
-> DIAG if exactly diagonal (fusion.is_diagonal) else DENSE; id and barrier are
skipped; anything else raises.
"""
import struct
import subprocess
from enum import IntEnum
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import UnitaryGate

from circuits import QUEST_BASIS
from fusion import is_diagonal

RUNNER = Path(__file__).resolve().parent / "runtime" / "build" / "quest-linux" / "quest_runner"

MAGIC = b"QOPS"
VERSION = 1


class Op(IntEnum):
    H = 0
    X = 1
    Y = 2
    Z = 3
    S = 4
    T = 5
    PHASE = 6
    RX = 7
    RY = 8
    RZ = 9
    CX = 10
    CY = 11
    CZ = 12
    CRX = 13
    CRY = 14
    CRZ = 15
    CP = 16
    SWAP = 17
    DENSE = 18
    DIAG = 19


# Qiskit name -> (opcode, expected number of qubits); parameters are copied as given
_NATIVE = {
    "h": (Op.H, 1), "x": (Op.X, 1), "y": (Op.Y, 1), "z": (Op.Z, 1),
    "s": (Op.S, 1), "t": (Op.T, 1), "p": (Op.PHASE, 1),
    "rx": (Op.RX, 1), "ry": (Op.RY, 1), "rz": (Op.RZ, 1),
    "cx": (Op.CX, 2), "cy": (Op.CY, 2), "cz": (Op.CZ, 2),
    "crx": (Op.CRX, 2), "cry": (Op.CRY, 2), "crz": (Op.CRZ, 2),
    "cp": (Op.CP, 2), "swap": (Op.SWAP, 2),
}
_FIXED_PHASE = {"sdg": -np.pi / 2, "tdg": -np.pi / 4}
_AS_DENSE = {"u", "sx", "sxdg"}
_SKIP = {"id", "barrier"}


def encode(qc):
    """List of (opcode, qubits, params, matrix-or-None) for qc, following the mapping above."""
    ops = []
    for inst in qc.data:
        op = inst.operation
        name = op.name
        qubits = [qc.find_bit(q).index for q in inst.qubits]
        if name in _SKIP:
            continue
        if name in _NATIVE:
            code, nq = _NATIVE[name]
            if len(qubits) != nq:
                raise ValueError(f"{name} on {len(qubits)} qubits, expected {nq}")
            ops.append((code, qubits, [float(p) for p in op.params], None))
        elif name in _FIXED_PHASE:
            ops.append((Op.PHASE, qubits, [_FIXED_PHASE[name]], None))
        elif name in _AS_DENSE:
            ops.append((Op.DENSE, qubits, [], np.asarray(op.to_matrix(), dtype=complex)))
        elif name == "unitary":
            m = np.asarray(op.to_matrix(), dtype=complex)
            if is_diagonal(op):
                ops.append((Op.DIAG, qubits, [], np.diagonal(m).copy()))
            else:
                ops.append((Op.DENSE, qubits, [], m))
        else:
            raise ValueError(f"gate '{name}' has no .qops mapping (transpile to QUEST_BASIS first)")
    return ops


def write_qops(qc, path):
    """Write qc as a .qops file. Returns the number of ops written."""
    ops = encode(qc)
    out = bytearray(MAGIC)
    out += struct.pack("<III", VERSION, qc.num_qubits, len(ops))
    for code, qubits, params, mat in ops:
        k = len(qubits)
        out += struct.pack("<BB", int(code), k)
        out += struct.pack(f"<{k}I", *qubits)
        out += struct.pack("<B", len(params))
        out += struct.pack(f"<{len(params)}d", *params)
        if code == Op.DENSE:
            assert mat.shape == (2**k, 2**k)
            out += np.ascontiguousarray(mat, dtype="<c16").tobytes()
        elif code == Op.DIAG:
            assert mat.shape == (2**k,)
            out += np.ascontiguousarray(mat, dtype="<c16").tobytes()
    with open(path, "wb") as f:
        f.write(out)
    return len(ops)


def read_qops(path):
    """Decode a .qops file back into a Qiskit circuit (reference decoder for testing the writer)."""
    data = open(path, "rb").read()
    if data[:4] != MAGIC:
        raise ValueError(f"{path}: bad magic {data[:4]!r}")
    version, n, num_ops = struct.unpack_from("<III", data, 4)
    if version != VERSION:
        raise ValueError(f"{path}: version {version}, expected {VERSION}")
    pos = 16
    qc = QuantumCircuit(n)
    for _ in range(num_ops):
        code, k = struct.unpack_from("<BB", data, pos); pos += 2
        qubits = list(struct.unpack_from(f"<{k}I", data, pos)); pos += 4 * k
        (npar,) = struct.unpack_from("<B", data, pos); pos += 1
        params = list(struct.unpack_from(f"<{npar}d", data, pos)); pos += 8 * npar
        code = Op(code)
        if code == Op.DENSE:
            m = np.frombuffer(data, "<c16", 4**k, pos).reshape(2**k, 2**k); pos += 16 * 4**k
            qc.append(UnitaryGate(m, check_input=False), qubits)
        elif code == Op.DIAG:
            d = np.frombuffer(data, "<c16", 2**k, pos); pos += 16 * 2**k
            qc.append(UnitaryGate(np.diag(d), check_input=False), qubits)
        else:
            name = {Op.PHASE: "p"}.get(code, code.name.lower())
            getattr(qc, name)(*params, *qubits)
    if pos != len(data):
        raise ValueError(f"{path}: {len(data) - pos} trailing bytes")
    return qc


def read_amps(path, n):
    """Amplitudes written by quest_runner --verify: 2^n complex128, little-endian."""
    amps = np.fromfile(path, dtype="<c16")
    if amps.size != 2**n:
        raise ValueError(f"{path}: {amps.size} amplitudes, expected 2^{n} = {2**n}")
    return amps


# --------------------------------------------------------------------------- runner

def run_runner(args, env=None, runner=RUNNER):
    """Run quest_runner with args; returns its stdout lines."""
    proc = subprocess.run([str(runner), *map(str, args)], env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"quest_runner failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.splitlines()


def parse_times(lines, count):
    """Per-plan lists of timed reps from the runner's RESULT,<plan>,<rep>,<seconds> lines."""
    times = [[] for _ in range(count)]
    for line in lines:
        if line.startswith("RESULT,"):
            _, idx, _, sec = line.split(",")
            times[int(idx)].append(float(sec))
    return times
