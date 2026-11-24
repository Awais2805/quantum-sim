# Fusion on QuEST

Host ar-mbp, 8 threads, best of 3 round-robin reps, rqc seed 1111+n, cost table results/ar-mbp2/cost_table_quest_t8_n24.json.

Cell: best simulation time · speedup vs unfused · ops applied · fusion-pass time. **Bold** = fastest.

## qft

| config | n=14 (865866597a70) | n=16 (768d7310f026) | n=18 (9fdf24249a05) | n=20 (5c8f75ab570b) |
|---|---|---|---|---|
| none | 4.9 ms · 1.00× · 112 ops · 0 ms | 10.3 ms · 1.00× · 144 ops · 0 ms | 44.4 ms · 1.00× · 180 ops · 0 ms | 102.7 ms · 1.00× · 220 ops · 0 ms |
| aer | 5.0 ms · 0.98× · 40 ops · 10 ms | 11.4 ms · 0.90× · 51 ops · 18 ms | 26.5 ms · 1.68× · 62 ops · 18 ms | 126.2 ms · 0.81× · 75 ops · 31 ms |
| dp | 1.3 ms · 3.84× · 47 ops · 17 ms | 7.5 ms · 1.38× · 58 ops · 26 ms | 22.2 ms · 2.00× · 70 ops · 31 ms | 109.2 ms · 0.94× · 83 ops · 46 ms |
| diag+dp | 1.7 ms · 2.84× · 48 ops · 12 ms | 7.7 ms · 1.34× · 60 ops · 16 ms | 42.0 ms · 1.06× · 72 ops · 20 ms | 114.5 ms · 0.90× · 86 ops · 30 ms |
| diag8 | 1.0 ms · 4.93× · 37 ops · 103 ms | 6.1 ms · 1.70× · 45 ops · 151 ms | 17.4 ms · 2.55× · 53 ops · 171 ms | 69.2 ms · 1.49× · 61 ops · 207 ms |
| diag8+dp | **0.9 ms · 5.70× · 31 ops · 193 ms** | **5.6 ms · 1.84× · 39 ops · 174 ms** | **14.6 ms · 3.04× · 47 ops · 239 ms** | **68.6 ms · 1.50× · 55 ops · 253 ms** |

## rqc

| config | n=14 (ef3f04e27aec) | n=16 (b65280b3ebf0) | n=18 (1ffa13b80759) | n=20 (56fd548885f6) |
|---|---|---|---|---|
| none | 7.1 ms · 1.00× · 357 ops · 0 ms | 20.4 ms · 1.00× · 472 ops · 0 ms | 93.7 ms · 1.00× · 632 ops · 0 ms | 560.7 ms · 1.00× · 958 ops · 0 ms |
| aer | 1.9 ms · 3.64× · 41 ops · 31 ms | 10.0 ms · 2.04× · 60 ops · 41 ms | 36.4 ms · 2.58× · 54 ops · 56 ms | 316.3 ms · 1.77× · 109 ops · 83 ms |
| dp | **1.2 ms · 5.79× · 66 ops · 34 ms** | **4.8 ms · 4.23× · 95 ops · 46 ms** | **17.6 ms · 5.31× · 91 ops · 60 ms** | **147.1 ms · 3.81× · 182 ops · 95 ms** |
| diag+dp | 1.5 ms · 4.88× · 71 ops · 42 ms | 5.4 ms · 3.75× · 101 ops · 51 ms | 20.2 ms · 4.64× · 96 ops · 65 ms | 164.0 ms · 3.42× · 192 ops · 96 ms |
| diag8 | 4.6 ms · 1.55× · 229 ops · 84 ms | 14.3 ms · 1.42× · 308 ops · 99 ms | 58.6 ms · 1.60× · 386 ops · 150 ms | 340.0 ms · 1.65× · 588 ops · 330 ms |
| diag8+dp | 2.6 ms · 2.69× · 120 ops · 122 ms | 9.4 ms · 2.17× · 157 ops · 139 ms | 39.9 ms · 2.35× · 183 ops · 218 ms | 259.6 ms · 2.16× · 335 ops · 383 ms |

