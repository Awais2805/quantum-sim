# Fusion on QuEST

Host ar-mbp, 4 threads, best of 1 round-robin reps, rqc seed 1234, cost table: measured at each benchmark n.

Cell: best simulation time · speedup vs unfused · ops applied · fusion-pass time. **Bold** = fastest. † = cost table measured at a different n than this column.

## qft

| config | n=20 (5c8f75ab570b) | n=22 (2fa844c6039a) | n=24 (dfe9a5b91c5a) |
|---|---|---|---|
| none | **181.9 ms · 1.00× · 220 ops · 0 ms** | 939.4 ms · 1.00× · 264 ops · 0 ms | 8.51 s · 1.00× · 312 ops · 0 ms |
| aer | 237.1 ms · 0.77× · 75 ops · 22 ms | 1.21 s · 0.78× · 88 ops · 39 ms | 8.03 s · 1.06× · 103 ops · 61 ms |
| dp | 183.0 ms · 0.99× · 200 ops · 26 ms | **904.2 ms · 1.04× · 242 ops · 66 ms** | **6.25 s · 1.36× · 123 ops · 58 ms** |

## rqc

| config | n=20 (ee076f323509) | n=22 (d83ac9c12e4f) | n=24 (47200872c622) |
|---|---|---|---|
| none | 1.22 s · 1.00× · 659 ops · 0 ms | 4.12 s · 1.00× · 749 ops · 0 ms | 29.56 s · 1.00× · 910 ops · 0 ms |
| aer | 298.0 ms · 4.09× · 56 ops · 59 ms | 1.31 s · 3.14× · 66 ops · 62 ms | 7.23 s · 4.09× · 74 ops · 80 ms |
| dp | **132.9 ms · 9.17× · 94 ops · 64 ms** | **615.1 ms · 6.70× · 111 ops · 78 ms** | **4.38 s · 6.75× · 121 ops · 92 ms** |

