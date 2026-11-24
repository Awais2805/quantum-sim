# Gate fusion on Aer vs QuEST, 24 qubits

Machine: `qbench` (AMD EPYC 7763 64-Core Processor), 2 threads. Max fused width k = 2, 3, 4. Time = best of the timed runs (`sim_min_s`), simulation only. The fusion pass (our Python transpiler step, run once before simulating) is timed separately in the *fusion pass* column; *% of total* = fusion pass / (fusion pass + simulation). Aer built-in fusion runs inside the simulator, so its cost is already in the simulation time.
Speedups are against **Aer with no fusion** unless the column says otherwise. Rows with k = – choose their own block sizes.

## QFT (24 qubits, 3 timed run(s) per row)

| simulator | method | k | gates applied | time (s) | speedup vs Aer, no fusion | speedup vs same simulator, no fusion | ms per gate | fusion pass (s) | % of total |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Aer | no fusion | – | 312 | 2.892 | 1.00× | 1.00× | 9.27 | – | – |
| Aer | Aer built-in fusion | – | 103 | 4.653 | 0.62× | 0.62× | 45.17 | in sim | – |
| Aer | horizontal, greedy | 2 | 288 | 3.828 | 0.76× | 0.76× | 13.29 | 0.014 | 0.37% |
| Aer | horizontal, cost model | 2 | 312 | 2.885 | 1.00× | 1.00× | 9.25 | 0.039 | 1.34% |
| Aer | vertical, greedy | 2 | 312 | 2.970 | 0.97× | 0.97× | 9.52 | 0.005 | 0.18% |
| Aer | vertical, cost model | 2 | 312 | 2.898 | 1.00× | 1.00× | 9.29 | 0.005 | 0.18% |
| Aer | horizontal, greedy | 3 | 146 | 6.678 | 0.43× | 0.43× | 45.74 | 0.049 | 0.73% |
| Aer | horizontal, cost model | 3 | 312 | 2.898 | 1.00× | 1.00× | 9.29 | 0.065 | 2.20% |
| Aer | vertical, greedy | 3 | 289 | 4.635 | 0.62× | 0.62× | 16.04 | 0.012 | 0.25% |
| Aer | vertical, cost model | 3 | 312 | 2.894 | 1.00× | 1.00× | 9.28 | 0.017 | 0.59% |
| Aer | horizontal, greedy | 4 | 94 | 6.546 | 0.44× | 0.44× | 69.64 | 0.046 | 0.70% |
| Aer | horizontal, cost model | 4 | 312 | 2.907 | 0.99× | 0.99× | 9.32 | 0.115 | 3.80% |
| Aer | vertical, greedy | 4 | 168 | 9.252 | 0.31× | 0.31× | 55.07 | 0.051 | 0.55% |
| Aer | vertical, cost model | 4 | 312 | 2.893 | 1.00× | 1.00× | 9.27 | 0.071 | 2.39% |
| QuEST | no fusion | – | 312 | 3.311 | 0.87× | 1.00× | 10.61 | – | – |
| QuEST | measured-cost fusion | – | 288 | 3.225 | 0.90× | 1.03× | 11.20 | 0.033 | 1.01% |
| QuEST | horizontal, greedy | 2 | 288 | 3.218 | 0.90× | 1.03× | 11.17 | 0.039 | 1.21% |
| QuEST | horizontal, cost model | 2 | 288 | 3.283 | 0.88× | 1.01× | 11.40 | 0.022 | 0.67% |
| QuEST | vertical, greedy | 2 | 312 | 3.299 | 0.88× | 1.00× | 10.57 | 0.005 | 0.16% |
| QuEST | vertical, cost model | 2 | 312 | 3.375 | 0.86× | 0.98× | 10.82 | 0.028 | 0.81% |
| QuEST | horizontal, greedy | 3 | 146 | 5.847 | 0.49× | 0.57× | 40.05 | 0.049 | 0.84% |
| QuEST | horizontal, cost model | 3 | 288 | 3.283 | 0.88× | 1.01× | 11.40 | 0.072 | 2.13% |
| QuEST | vertical, greedy | 3 | 289 | 5.212 | 0.55× | 0.64× | 18.03 | 0.012 | 0.23% |
| QuEST | vertical, cost model | 3 | 312 | 3.365 | 0.86× | 0.98× | 10.78 | 0.017 | 0.51% |
| QuEST | horizontal, greedy | 4 | 94 | 5.744 | 0.50× | 0.58× | 61.11 | 0.047 | 0.81% |
| QuEST | horizontal, cost model | 4 | 288 | 3.273 | 0.88× | 1.01× | 11.37 | 0.118 | 3.47% |
| QuEST | vertical, greedy | 4 | 168 | 8.058 | 0.36× | 0.41× | 47.97 | 0.052 | 0.64% |
| QuEST | vertical, cost model | 4 | 312 | 3.369 | 0.86× | 0.98× | 10.80 | 0.070 | 2.05% |

Noise check (the unfused circuit timed twice): Aer +0.3%, QuEST -0.3%

## Random circuit (24 qubits, 1 timed run(s) per row)

| simulator | method | k | gates applied | time (s) | speedup vs Aer, no fusion | speedup vs same simulator, no fusion | ms per gate | fusion pass (s) | % of total |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Aer | no fusion | – | 1236 | 19.502 | 1.00× | 1.00× | 15.78 | – | – |
| Aer | Aer built-in fusion | – | 134 | 12.155 | 1.60× | 1.60× | 90.71 | in sim | – |
| Aer | horizontal, greedy | 2 | 231 | 14.961 | 1.30× | 1.30× | 64.77 | 0.114 | 0.76% |
| Aer | horizontal, cost model | 2 | 474 | 13.329 | 1.46× | 1.46× | 28.12 | 0.184 | 1.36% |
| Aer | vertical, greedy | 2 | 835 | 29.142 | 0.67× | 0.67× | 34.90 | 0.110 | 0.38% |
| Aer | vertical, cost model | 2 | 1236 | 19.583 | 1.00× | 1.00× | 15.84 | 0.114 | 0.58% |
| Aer | horizontal, greedy | 3 | 143 | 12.505 | 1.56× | 1.56× | 87.44 | 0.102 | 0.81% |
| Aer | horizontal, cost model | 3 | 266 | 11.504 | 1.70× | 1.70× | 43.25 | 0.204 | 1.74% |
| Aer | vertical, greedy | 3 | 579 | 51.082 | 0.38× | 0.38× | 88.22 | 0.155 | 0.30% |
| Aer | vertical, cost model | 3 | 1214 | 19.396 | 1.01× | 1.01× | 15.98 | 0.268 | 1.36% |
| Aer | horizontal, greedy | 4 | 117 | 13.454 | 1.45× | 1.45× | 114.99 | 0.100 | 0.74% |
| Aer | horizontal, cost model | 4 | 210 | 11.805 | 1.65× | 1.65× | 56.21 | 0.232 | 1.93% |
| Aer | vertical, greedy | 4 | 452 | 72.385 | 0.27× | 0.27× | 160.14 | 0.148 | 0.20% |
| Aer | vertical, cost model | 4 | 1177 | 19.355 | 1.01× | 1.01× | 16.44 | 0.398 | 2.01% |
| QuEST | no fusion | – | 1236 | 15.298 | 1.27× | 1.00× | 12.38 | – | – |
| QuEST | measured-cost fusion | – | 223 | 4.095 | 4.76× | 3.74× | 18.36 | 0.112 | 2.67% |
| QuEST | horizontal, greedy | 2 | 231 | 4.187 | 4.66× | 3.65× | 18.12 | 0.135 | 3.13% |
| QuEST | horizontal, cost model | 2 | 234 | 4.255 | 4.58× | 3.60× | 18.18 | 0.245 | 5.44% |
| QuEST | vertical, greedy | 2 | 835 | 11.454 | 1.70× | 1.34× | 13.72 | 0.109 | 0.94% |
| QuEST | vertical, cost model | 2 | 835 | 11.603 | 1.68× | 1.32× | 13.90 | 0.219 | 1.85% |
| QuEST | horizontal, greedy | 3 | 143 | 10.102 | 1.93× | 1.51× | 70.64 | 0.101 | 0.99% |
| QuEST | horizontal, cost model | 3 | 178 | 7.702 | 2.53× | 1.99× | 43.27 | 0.227 | 2.87% |
| QuEST | vertical, greedy | 3 | 579 | 47.642 | 0.41× | 0.32× | 82.28 | 0.156 | 0.33% |
| QuEST | vertical, cost model | 3 | 855 | 12.467 | 1.56× | 1.23× | 14.58 | 0.340 | 2.65% |
| QuEST | horizontal, greedy | 4 | 117 | 10.324 | 1.89× | 1.48× | 88.24 | 0.101 | 0.97% |
| QuEST | horizontal, cost model | 4 | 156 | 8.103 | 2.41× | 1.89× | 51.94 | 0.244 | 2.92% |
| QuEST | vertical, greedy | 4 | 452 | 59.273 | 0.33× | 0.26× | 131.13 | 0.150 | 0.25% |
| QuEST | vertical, cost model | 4 | 834 | 12.265 | 1.59× | 1.25× | 14.71 | 0.440 | 3.46% |

Noise check (the unfused circuit timed twice): Aer -0.2%, QuEST +0.1%

## Reproduce

```
cd fusion_study && tmux new -d -s meeting 'N=24 bash meeting_run.sh'
python plot_meeting.py results/meeting_n24
```

## Environment (ENV.txt)

```
date: 2026-11-10T11:40:42+00:00
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
threads: 2   n: 24   widths: 2,3,4   reps: qft 3, rqc 1
2b3ec0cb14da1e60889c29e3598c1801  fusion_bench.py
ca62bf607df4ffb01e5bf8737a712d80  quest_bench.py
ce6ace6526f8fde81a8c818cc5f533a7  quest_ops.py
db608f619e8c1b8c3bd8dc3d7c4132d0  dp_fusion.py
46ae86772dcc298be8f5d6649ba44ca4  quest_runner.cpp
beecdc451672d2189c47647c7bacbd98  aer_fused_count.py
0e4df9aded1c877b925fe27117f29885  meeting_run.sh
```
