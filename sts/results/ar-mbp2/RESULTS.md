# Fusion on QuEST

Host ar-mbp, 8 threads, best of 3 round-robin reps, rqc seed 1111+n, cost table cost_table_quest_t8_n24.json.

Cell: best simulation time · speedup vs unfused · ops applied · fusion-pass time. **Bold** = fastest.

## qft

| config | n=20 (5c8f75ab570b) | n=22 (2fa844c6039a) |
|---|---|---|
| none | 125.2 ms · 1.00× · 220 ops · 0 ms | 795.3 ms · 1.00× · 264 ops · 0 ms |
| aer | 145.9 ms · 0.86× · 75 ops · 54 ms | 703.3 ms · 1.13× · 88 ops · 30 ms |
| dp | 123.9 ms · 1.01× · 83 ops · 49 ms | 701.1 ms · 1.13× · 97 ops · 75 ms |
| diag+dp | 140.8 ms · 0.89× · 86 ops · 29 ms | 609.2 ms · 1.31× · 100 ops · 30 ms |
| diag8 | 77.6 ms · 1.61× · 61 ops · 443 ms | **371.5 ms · 2.14× · 70 ops · 344 ms** |
| diag8+dp | **73.9 ms · 1.69× · 55 ops · 462 ms** | 578.1 ms · 1.38× · 64 ops · 403 ms |

## rqc

| config | n=20 (56fd548885f6) | n=22 (32d67f62ec01) |
|---|---|---|
| none | 603.5 ms · 1.00× · 958 ops · 0 ms | 3.25 s · 1.00× · 747 ops · 0 ms |
| aer | 350.4 ms · 1.72× · 109 ops · 117 ms | 672.2 ms · 4.84× · 58 ops · 66 ms |
| dp | **152.8 ms · 3.95× · 182 ops · 131 ms** | **305.6 ms · 10.65× · 100 ops · 79 ms** |
| diag+dp | 174.5 ms · 3.46× · 192 ops · 556 ms | 459.6 ms · 7.08× · 116 ops · 86 ms |
| diag8 | 407.2 ms · 1.48× · 588 ops · 383 ms | 2.65 s · 1.23× · 475 ops · 197 ms |
| diag8+dp | 281.4 ms · 2.14× · 335 ops · 906 ms | 1.18 s · 2.75× · 197 ops · 369 ms |

