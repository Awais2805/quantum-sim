# qiskit-lab

| Path | What it is |
|---|---|
| `.venv/` | Python env (qiskit 2.6.1, qiskit-aer 0.18.2). Scripts in `fusion_study/` use `../.venv/bin/python`. |
| `fusion_study/` | Gate-fusion study: Qiskit-fused QFT / random circuits timed on Aer and on QuEST. |
| `scaling_study/` | Earlier qubit-scaling experiment (`qubit_scaling.py` + its helpers `swap_mode.sh`, `svsim_slice.sh`) and its outputs. |
| `notebooks/` | Scratch notebook (`Untitled.ipynb`, formerly in `QisKit Sim/`). |

## fusion_study/

**Code**

| File | Purpose |
|---|---|
| `fusion_bench.py` | Builds circuits and fusion variants; Aer timing sweep. |
| `quest_bench.py` | Same variants, timed on QuEST. |
| `plot_fusion.py` | Plots any results CSV (4 PNGs per CSV). |
| `quest_runner.cpp` + `build_quest.sh` | Op-file interpreter that runs the circuits on QuEST. Build output goes to `build/quest-linux/`. |
| `quest_ops.py`, `verify_quest.py` | `.qops` writer and the QuEST mapping test. |
| `dp_fusion.py` | Python port of Aer's fuser (`dp`, `diag+dp`). |

**Results** (`fusion_study/results/`)

| Folder | Contents |
|---|---|
| `aer_laptop/` | Aer, laptop, QFT, n = 4–26, k = 2/3/4. |
| `vm/` | Aer, qbench VM, QFT + RQC, n = 5–28, greedy and cost-model, k = 4. Also `first_server_run/` (the first VM run) and `single_point_n26/` (old n = 26-only plots). |
| `quest_laptop/` | QuEST phase 1: laptop, n = 16–22, horizontal / vertical / both. |
| `quest_laptop2/` | QuEST phase 2: all modes, plus a cost-model pass. |
| `smoke/` | Small-n smoke tests and cost tables. `check_killed_run/` holds a partial run that was stopped. |
