# Fusion on QuEST

Host ar-mbp, 4 threads, best of 5 round-robin reps, rqc seed 1234+n, cost table cost_table_quest_t4_n24.json.

Cell: best simulation time · speedup vs unfused · ops applied · fusion-pass time. **Bold** = fastest.

## qft

| config | n=20 (5c8f75ab570b) | n=22 (2fa844c6039a) | n=24 (dfe9a5b91c5a) |
|---|---|---|---|
| none | 180.2 ms · 1.00× · 220 ops · 0 ms | 865.7 ms · 1.00× · 264 ops · 0 ms | 5.94 s · 1.00× · 312 ops · 0 ms |
| aer | 229.0 ms · 0.79× · 75 ops · 27 ms | 1.10 s · 0.79× · 88 ops · 26 ms | 6.16 s · 0.96× · 103 ops · 41 ms |
| dp | 189.1 ms · 0.95× · 92 ops · 63 ms | 912.7 ms · 0.95× · 107 ops · 46 ms | 4.77 s · 1.24× · 123 ops · 53 ms |
| diag+dp | 196.9 ms · 0.92× · 96 ops · 28 ms | 951.2 ms · 0.91× · 110 ops · 30 ms | 5.39 s · 1.10× · 128 ops · 34 ms |
| diag8 | 124.8 ms · 1.44× · 61 ops · 219 ms | 591.3 ms · 1.46× · 70 ops · 334 ms | 3.22 s · 1.85× · 80 ops · 363 ms |
| diag8+dp | **123.0 ms · 1.46× · 59 ops · 309 ms** | **586.1 ms · 1.48× · 68 ops · 364 ms** | **3.13 s · 1.90× · 78 ops · 430 ms** |

## rqc

| config | n=20 (79e8aa069b8a) | n=22 (1f2aa6da7213) | n=24 (3479b166ed7e) |
|---|---|---|---|
| none | 830.2 ms · 1.00× · 787 ops · 0 ms | 3.46 s · 1.00× · 678 ops · 0 ms | 29.15 s · 1.00× · 1236 ops · 0 ms |
| aer | 360.8 ms · 2.30× · 76 ops · 74 ms | 671.1 ms · 5.15× · 39 ops · 59 ms | 13.66 s · 2.13× · 135 ops · 115 ms |
| dp | **167.4 ms · 4.96× · 123 ops · 78 ms** | **318.4 ms · 10.86× · 58 ops · 64 ms** | **6.99 s · 4.17× · 217 ops · 129 ms** |
| diag+dp | 211.3 ms · 3.93× · 147 ops · 89 ms | 404.3 ms · 8.55× · 67 ops · 70 ms | 7.96 s · 3.66× · 234 ops · 130 ms |
| diag8 | 501.8 ms · 1.65× · 478 ops · 192 ms | 2.22 s · 1.56× · 414 ops · 172 ms | 19.14 s · 1.52× · 726 ops · 456 ms |
| diag8+dp | 361.0 ms · 2.30× · 243 ops · 257 ms | 983.7 ms · 3.51× · 152 ops · 239 ms | 13.44 s · 2.17× · 384 ops · 542 ms |

