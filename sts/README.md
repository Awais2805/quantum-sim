# sts: circuit compiler passes + QuEST runtime

## Process

```
Qiskit circuit ──► fusion pass ──► .qops plan ──► quest_runner (stock QuEST v4.2)
 circuits.py       fusion.py        qops.py        runtime/
                     ▲
                 cost model
                  costs.py
```

1. **Circuit** (`circuits.py`): QFT or random circuit, in the gate set the runner accepts.
2. **Fuse** (`fusion.py`): Aer's fuser (DiagonalFusion → NQubitFusion → CostBasedFusion DP), ported to Python so it runs offline at any n, with no Aer at runtime. Decisions come from either Aer's hard-coded costs (`"aer"`, which gives exactly Aer's plan) or a cost table (`dict`). Also `diagonal_blocks`: DAG-wise merging of diagonal gates (experimental, no cost check yet).
3. **Cost table** (`costs.py`): seconds per gate kind (`h/1`, `cp/2`, `dense/w`, `diag/w`), every kind measured on stock QuEST on this machine (8 copies on random qubits, best of 3), **one table per benchmark n** (`cost_table_quest_t<threads>_n<n>.json`). Re-measure per machine, thread count and memory tier. Forcing one table for all n (`--n-cal`, `--table`) is allowed but flagged (`table_n` column, † in RESULTS.md).
4. **Plan** (`qops.py`): binary op list. Fused blocks become `DIAG` if exactly diagonal, otherwise `DENSE`.
5. **Run** (`runtime/quest_runner.cpp`): one QuEST call per op (`applyCompMatr*` / `applyDiagMatr*` for fused blocks).

New techniques (swap elimination, cache blocking, staging) go in as further passes between steps 2 and 4. They work on the same op list and are priced by the same cost table.

## Use

```
./runtime/build_quest.sh                     # builds QuEST + runtime/build/quest-linux/quest_runner
python verify.py                             # mapping, port == Aer, fused == unfused (~5 s)
python bench.py --ns 18 20 22 --threads 4    # one thread per physical core; -> results/<host>/bench.csv, RESULTS.md
```

Python: `../qiskit-lab/.venv/bin/python` (qiskit 2.6.1, qiskit-aer 0.18.2; Aer is only needed by `verify.py port`).

## Files

| file | role |
|---|---|
| `circuits.py` | benchmark circuits, `QUEST_BASIS`, fingerprint |
| `fusion.py` | fusion pass (Aer port + table-priced variant + diagonal blocks) |
| `costs.py` | cost table: measure every gate kind on QuEST, load |
| `graph.py` | plot bench.csv vs n: speedup, sim time, fusion-pass time, total (`--plots`, `--stat`, `--configs`) |
| `qops.py` | `.qops` writer/reader, runner helpers |
| `verify.py` | all correctness checks |
| `bench.py` | times `none` (stock QuEST), `aer` (Aer's plan) and `dp` (ours) on QuEST; `--configs ... diag8+dp` adds the experimental diagonal pass |
| `runtime/` | `quest_runner.cpp`, `build_quest.sh` |

Older results (made by the pre-debloat scripts, commit 97add8b) are in `../misc/fusion_study/results/` (old scripts are alongside, in `../misc/`).
