# Gate fusion on Aer vs QuEST, 26 qubits

Machine: `qbench` (AMD EPYC 7763 64-Core Processor), 2 threads. Max fused width k = 2. Time = best of the timed runs (`sim_min_s`), simulation only. The fusion pass (our Python transpiler step, run once before simulating) is timed separately in the *fusion pass* column; *% of total* = fusion pass / (fusion pass + simulation). Aer built-in fusion runs inside the simulator, so its cost is already in the simulation time.
Speedups are against **Aer with no fusion** unless the column says otherwise. Rows with k = – choose their own block sizes.

## QFT (26 qubits, 2 timed run(s) per row)

| simulator | method | k | gates applied | time (s) | speedup vs Aer, no fusion | speedup vs same simulator, no fusion | ms per gate | fusion pass (s) | % of total |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Aer | no fusion | – | 364 | 13.631 | 1.00× | 1.00× | 37.45 | – | – |
| Aer | Aer built-in fusion | – | 118 | 22.071 | 0.62× | 0.62× | 187.05 | in sim | – |
| Aer | horizontal, greedy | 2 | 338 | 18.950 | 0.72× | 0.72× | 56.07 | 0.016 | 0.08% |
| Aer | horizontal, cost model | 2 | 364 | 13.772 | 0.99× | 0.99× | 37.83 | 0.043 | 0.31% |
| Aer | vertical, greedy | 2 | 364 | 13.208 | 1.03× | 1.03× | 36.28 | 0.006 | 0.05% |
| Aer | vertical, cost model | 2 | 364 | 13.202 | 1.03× | 1.03× | 36.27 | 0.006 | 0.05% |
| QuEST | no fusion | – | 364 | 15.822 | 0.86× | 1.00× | 43.47 | – | – |
| QuEST | measured-cost fusion | – | 338 | 15.449 | 0.88× | 1.02× | 45.71 | 0.040 | 0.26% |
| QuEST | horizontal, greedy | 2 | 338 | 15.563 | 0.88× | 1.02× | 46.05 | 0.043 | 0.28% |
| QuEST | horizontal, cost model | 2 | 338 | 15.568 | 0.88× | 1.02× | 46.06 | 0.047 | 0.30% |
| QuEST | vertical, greedy | 2 | 364 | 15.759 | 0.86× | 1.00× | 43.29 | 0.006 | 0.04% |
| QuEST | vertical, cost model | 2 | 364 | 15.957 | 0.85× | 0.99× | 43.84 | 0.006 | 0.04% |

Noise check (the unfused circuit timed twice): Aer -0.4%, QuEST +0.2%

## Random circuit (26 qubits, 1 timed run(s) per row)

| simulator | method | k | gates applied | time (s) | speedup vs Aer, no fusion | speedup vs same simulator, no fusion | ms per gate | fusion pass (s) | % of total |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Aer | no fusion | – | 1411 | 103.650 | 1.00× | 1.00× | 73.46 | – | – |
| Aer | Aer built-in fusion | – | 162 | 67.575 | 1.53× | 1.53× | 417.13 | in sim | – |
| Aer | horizontal, greedy | 2 | 282 | 85.880 | 1.21× | 1.21× | 304.54 | 0.130 | 0.15% |
| Aer | horizontal, cost model | 2 | 894 | 76.636 | 1.35× | 1.35× | 85.72 | 0.179 | 0.23% |
| Aer | vertical, greedy | 2 | 957 | 154.021 | 0.67× | 0.67× | 160.94 | 0.123 | 0.08% |
| Aer | vertical, cost model | 2 | 1411 | 99.625 | 1.04× | 1.04× | 70.61 | 0.130 | 0.13% |
| QuEST | no fusion | – | 1411 | 75.575 | 1.37× | 1.00× | 53.56 | – | – |
| QuEST | measured-cost fusion | – | 274 | 21.793 | 4.76× | 3.47× | 79.54 | 0.132 | 0.60% |
| QuEST | horizontal, greedy | 2 | 282 | 22.327 | 4.64× | 3.38× | 79.17 | 0.152 | 0.67% |
| QuEST | horizontal, cost model | 2 | 284 | 22.239 | 4.66× | 3.40× | 78.31 | 0.280 | 1.24% |
| QuEST | vertical, greedy | 2 | 957 | 56.872 | 1.82× | 1.33× | 59.43 | 0.123 | 0.22% |
| QuEST | vertical, cost model | 2 | 957 | 56.112 | 1.85× | 1.35× | 58.63 | 0.247 | 0.44% |

## Reproduce

```
cd fusion_study && tmux new -d -s meeting 'N=26 bash meeting_run.sh'
python plot_meeting.py results/meeting_n26
```

## Environment (ENV.txt)

```
date: 2026-11-10T10:52:00+00:00
host: qbench
CPU(s):                                  2
Model name:                              AMD EPYC 7763 64-Core Processor
Thread(s) per core:                      1
L3 cache:                                32 MiB (1 instance)
               total        used        free      shared  buff/cache   available
Mem:              15           0          12           0           2          14
python 3.12.3
qiskit 2.6.1
qiskit-aer 0.18.2
threads: 2   n: 26
2b3ec0cb14da1e60889c29e3598c1801  fusion_bench.py
ca62bf607df4ffb01e5bf8737a712d80  quest_bench.py
ce6ace6526f8fde81a8c818cc5f533a7  quest_ops.py
db608f619e8c1b8c3bd8dc3d7c4132d0  dp_fusion.py
46ae86772dcc298be8f5d6649ba44ca4  quest_runner.cpp
beecdc451672d2189c47647c7bacbd98  aer_fused_count.py
aa30f96636d561cb2e6d931f0c6df3c7  meeting_n26.sh
```
