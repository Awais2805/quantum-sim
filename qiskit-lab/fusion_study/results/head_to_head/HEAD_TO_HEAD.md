# Head-to-head: Aer vs QuEST, no fusion vs Aer's fuser vs ours

Host ar-mbp, 4 threads, min of 3 round-robin reps, rqc seed 1234+n, cost tables at n=22. State check passed at n=10.

Every row of a table runs the **same circuit object** (rqc in QuEST's gate set on both simulators). Cells: fastest-rep time, then speedup vs **Aer · no fusion** (the common reference); in brackets, speedup vs the same simulator's no-fusion. **Bold** = fastest.

## qft

| configuration | n=18 (180 gates, 9fdf24249a05) | n=20 (220 gates, 5c8f75ab570b) | n=22 (264 gates, 2fa844c6039a) | n=24 (312 gates, dfe9a5b91c5a) |
|---|---|---|---|---|
| Aer · no fusion | 21.5 ms · 1.00× (1.00×) · 180 ops | **112.3 ms · 1.00× (1.00×) · 220 ops** | **542.2 ms · 1.00× (1.00×) · 264 ops** | 4.76 s · 1.00× (1.00×) · 312 ops |
| Aer · Aer built-in fusion | 55.2 ms · 0.39× (0.39×) · 180 ops | 235.9 ms · 0.48× (0.48×) · 220 ops | 2.18 s · 0.25× (0.25×) · 264 ops | 8.15 s · 0.58× (0.58×) · 312 ops |
| Aer · Aer fuser (offline port) | 43.9 ms · 0.49× (0.49×) · 62 ops | 235.5 ms · 0.48× (0.48×) · 75 ops | 2.09 s · 0.26× (0.26×) · 88 ops | 8.39 s · 0.57× (0.57×) · 103 ops |
| Aer · ours: dp (Aer costs) | 21.1 ms · 1.02× (1.02×) · 162 ops | 126.3 ms · 0.89× (0.89×) · 200 ops | 672.0 ms · 0.81× (0.81×) · 242 ops | 5.32 s · 0.89× (0.89×) · 288 ops |
| Aer · ours: diag+dp (Aer costs) | **20.0 ms · 1.08× (1.08×) · 162 ops** | 129.5 ms · 0.87× (0.87×) · 200 ops | 654.9 ms · 0.83× (0.83×) · 242 ops | 5.30 s · 0.90× (0.90×) · 288 ops |
| Aer · ours: diagonal k=8 | 68.5 ms · 0.31× (0.31×) · 53 ops | 252.3 ms · 0.45× (0.45×) · 61 ops | 1.45 s · 0.37× (0.37×) · 70 ops | 6.92 s · 0.69× (0.69×) · 80 ops |
| QuEST · no fusion | 37.7 ms · 0.57× (1.00×) · 180 ops | 181.1 ms · 0.62× (1.00×) · 220 ops | 862.8 ms · 0.63× (1.00×) · 264 ops | 6.82 s · 0.70× (1.00×) · 312 ops |
| QuEST · Aer fuser plan | 47.2 ms · 0.46× (0.80×) · 62 ops | 230.5 ms · 0.49× (0.79×) · 75 ops | 1.51 s · 0.36× (0.57×) · 88 ops | 7.30 s · 0.65× (0.93×) · 103 ops |
| QuEST · ours: dp (QuEST costs) | 35.7 ms · 0.60× (1.06×) · 162 ops | 173.1 ms · 0.65× (1.05×) · 200 ops | 1.25 s · 0.43× (0.69×) · 242 ops | 6.60 s · 0.72× (1.03×) · 288 ops |
| QuEST · ours: diag+dp (QuEST costs) | 35.8 ms · 0.60× (1.05×) · 162 ops | 174.0 ms · 0.65× (1.04×) · 200 ops | 1.29 s · 0.42× (0.67×) · 242 ops | 6.54 s · 0.73× (1.04×) · 288 ops |
| QuEST · ours: diagonal k=8 | 26.9 ms · 0.80× (1.40×) · 53 ops | 124.2 ms · 0.90× (1.46×) · 61 ops | 590.8 ms · 0.92× (1.46×) · 70 ops | **4.30 s · 1.11× (1.59×) · 80 ops** |

## rqc

| configuration | n=18 (775 gates, 377997754b5d) | n=20 (787 gates, 79e8aa069b8a) | n=22 (678 gates, 1f2aa6da7213) | n=24 (1236 gates, 3479b166ed7e) |
|---|---|---|---|---|
| Aer · no fusion | 618.6 ms · 1.00× (1.00×) · 775 ops | 1.28 s · 1.00× (1.00×) · 787 ops | 4.89 s · 1.00× (1.00×) · 678 ops | 39.37 s · 1.00× (1.00×) · 1236 ops |
| Aer · Aer built-in fusion | 118.9 ms · 5.20× (5.20×) · 775 ops | 396.3 ms · 3.23× (3.23×) · 787 ops | 1.23 s · 3.98× (3.98×) · 678 ops | 17.18 s · 2.29× (2.29×) · 1236 ops |
| Aer · Aer fuser (offline port) | 115.1 ms · 5.37× (5.37×) · 90 ops | 394.3 ms · 3.24× (3.24×) · 76 ops | 1.18 s · 4.15× (4.15×) · 39 ops | 17.06 s · 2.31× (2.31×) · 135 ops |
| Aer · ours: dp (Aer costs) | 89.8 ms · 6.89× (6.89×) · 260 ops | 349.1 ms · 3.66× (3.66×) · 233 ops | 1.27 s · 3.83× (3.83×) · 147 ops | 16.62 s · 2.37× (2.37×) · 346 ops |
| Aer · ours: diag+dp (Aer costs) | 106.4 ms · 5.81× (5.81×) · 238 ops | 424.8 ms · 3.01× (3.01×) · 239 ops | 1.54 s · 3.16× (3.16×) · 147 ops | 19.38 s · 2.03× (2.03×) · 352 ops |
| Aer · ours: diagonal k=8 | 203.8 ms · 3.03× (3.03×) · 467 ops | 902.4 ms · 1.42× (1.42×) · 478 ops | 4.69 s · 1.04× (1.04×) · 414 ops | 31.37 s · 1.26× (1.26×) · 726 ops |
| QuEST · no fusion | 205.4 ms · 3.01× (1.00×) · 775 ops | 836.4 ms · 1.53× (1.00×) · 787 ops | 3.84 s · 1.27× (1.00×) · 678 ops | 33.51 s · 1.17× (1.00×) · 1236 ops |
| QuEST · Aer fuser plan | 107.9 ms · 5.73× (1.90×) · 90 ops | 363.7 ms · 3.52× (2.30×) · 76 ops | 675.5 ms · 7.24× (5.69×) · 39 ops | 14.49 s · 2.72× (2.31×) · 135 ops |
| QuEST · ours: dp (QuEST costs) | **48.3 ms · 12.80× (4.25×) · 152 ops** | **182.4 ms · 7.01× (4.58×) · 127 ops** | **320.5 ms · 15.25× (12.00×) · 58 ops** | **7.50 s · 5.25× (4.47×) · 225 ops** |
| QuEST · ours: diag+dp (QuEST costs) | 59.6 ms · 10.37× (3.44×) · 155 ops | 212.3 ms · 6.02× (3.94×) · 151 ops | 404.6 ms · 12.08× (9.50×) · 67 ops | 9.06 s · 4.34× (3.70×) · 240 ops |
| QuEST · ours: diagonal k=8 | 125.9 ms · 4.91× (1.63×) · 467 ops | 504.3 ms · 2.54× (1.66×) · 478 ops | 2.66 s · 1.83× (1.44×) · 414 ops | 20.99 s · 1.88× (1.60×) · 726 ops |

