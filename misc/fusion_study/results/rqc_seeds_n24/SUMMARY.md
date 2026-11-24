# Random circuits at 24 qubits, averaged over 7 circuits

Seeds (circuit seed = seed + 24): 1000, 1234, 2000, 3000, 4000, 5000, 6000. Speedups are per circuit, then combined with the geometric mean; [min–max] is the range over circuits. Times are sim_min_s. *Fusion pass* = mean time of our Python fusion step (run once, before simulating); *% of total* = fusion pass / (fusion pass + simulation). Aer built-in fusion runs inside the simulator, so it is already in the simulation time.

| simulator | method | k | circuits | speedup vs Aer, no fusion | range | speedup vs same simulator, no fusion | range | mean time (s) | mean gates | fusion pass (s) | % of total |
|---|---|---:|---:|---:|---|---:|---|---:|---:|---:|---:|
| Aer | no fusion | – | 7 | 1.00× | 1.00–1.00× | 1.00× | 1.00–1.00× | 15.97 | 1011 | – | – |
| Aer | Aer built-in fusion | – | 7 | 1.95× | 1.34–3.75× | 1.95× | 1.34–3.75× | 9.23 | 1011 | in sim | – |
| Aer | horizontal, greedy | 2 | 7 | 1.54× | 1.10–2.68× | 1.54× | 1.10–2.68× | 11.39 | 174 | 0.090 | 0.86% |
| Aer | horizontal, greedy | 3 | 7 | 1.84× | 1.31–3.23× | 1.84× | 1.31–3.23× | 9.57 | 111 | 0.081 | 0.94% |
| Aer | horizontal, greedy | 4 | 7 | 1.70× | 1.18–3.07× | 1.70× | 1.18–3.07× | 10.40 | 95 | 0.080 | 0.87% |
| Aer | horizontal, cost model | 2 | 7 | 1.65× | 1.25–2.69× | 1.65× | 1.25–2.69× | 10.43 | 376 | 0.161 | 1.69% |
| Aer | horizontal, cost model | 3 | 7 | 1.92× | 1.40–3.22× | 1.92× | 1.40–3.22× | 9.05 | 224 | 0.164 | 1.94% |
| Aer | horizontal, cost model | 4 | 7 | 1.87× | 1.39–3.22× | 1.87× | 1.39–3.22× | 9.36 | 181 | 0.187 | 2.10% |
| Aer | vertical, greedy | 2 | 7 | 0.62× | 0.57–0.67× | 0.62× | 0.57–0.67× | 25.62 | 661 | 0.095 | 0.37% |
| Aer | vertical, greedy | 3 | 7 | 0.39× | 0.36–0.47× | 0.39× | 0.36–0.47× | 41.22 | 459 | 0.125 | 0.30% |
| Aer | vertical, greedy | 4 | 7 | 0.30× | 0.27–0.35× | 0.30× | 0.27–0.35× | 55.20 | 355 | 0.119 | 0.22% |
| Aer | vertical, cost model | 2 | 7 | 1.00× | 0.98–1.00× | 1.00× | 0.98–1.00× | 16.04 | 1011 | 0.100 | 0.63% |
| Aer | vertical, cost model | 3 | 7 | 1.00× | 0.99–1.01× | 1.00× | 0.99–1.01× | 15.97 | 998 | 0.227 | 1.40% |
| Aer | vertical, cost model | 4 | 7 | 1.00× | 0.99–1.01× | 1.00× | 0.99–1.01× | 15.95 | 978 | 0.337 | 2.07% |
| QuEST | no fusion | – | 7 | 1.27× | 1.21–1.32× | 1.00× | 1.00–1.00× | 12.65 | 1011 | – | – |
| QuEST | measured-cost fusion | – | 7 | 5.78× | 4.07–10.97× | 4.57× | 3.35–8.31× | 3.09 | 164 | 0.089 | 3.14% |
| QuEST | horizontal, greedy | 2 | 7 | 5.41× | 3.97–9.26× | 4.28× | 3.27–7.02× | 3.21 | 174 | 0.114 | 3.86% |
| QuEST | horizontal, greedy | 3 | 7 | 2.39× | 1.60–4.58× | 1.89× | 1.32–3.47× | 7.53 | 111 | 0.081 | 1.24% |
| QuEST | horizontal, greedy | 4 | 7 | 2.35× | 1.66–4.36× | 1.85× | 1.32–3.31× | 7.63 | 95 | 0.081 | 1.21% |
| QuEST | horizontal, cost model | 2 | 7 | 5.33× | 3.83–8.90× | 4.21× | 3.16–6.75× | 3.25 | 175 | 0.197 | 6.24% |
| QuEST | horizontal, cost model | 3 | 7 | 2.89× | 2.16–4.69× | 2.28× | 1.78–3.56× | 5.98 | 132 | 0.177 | 3.03% |
| QuEST | horizontal, cost model | 4 | 7 | 2.81× | 2.20–4.71× | 2.22× | 1.75–3.57× | 6.14 | 119 | 0.192 | 3.19% |
| QuEST | vertical, greedy | 2 | 7 | 1.70× | 1.62–1.81× | 1.34× | 1.30–1.37× | 9.46 | 661 | 0.096 | 1.02% |
| QuEST | vertical, greedy | 3 | 7 | 0.42× | 0.38–0.50× | 0.33× | 0.30–0.38× | 38.78 | 459 | 0.126 | 0.33% |
| QuEST | vertical, greedy | 4 | 7 | 0.34× | 0.31–0.40× | 0.27× | 0.24–0.31× | 47.86 | 355 | 0.122 | 0.26% |
| QuEST | vertical, cost model | 2 | 7 | 1.69× | 1.61–1.81× | 1.34× | 1.31–1.37× | 9.48 | 661 | 0.190 | 2.00% |
| QuEST | vertical, cost model | 3 | 7 | 1.60× | 1.55–1.72× | 1.26× | 1.23–1.30× | 10.04 | 675 | 0.287 | 2.80% |
| QuEST | vertical, cost model | 4 | 7 | 1.61× | 1.53–1.74× | 1.27× | 1.25–1.32× | 9.97 | 663 | 0.377 | 3.68% |

Best on average: **QuEST · measured-cost fusion** (5.78× vs Aer, no fusion).

## Per circuit (time in s; noise = control vs no fusion)

| seed | gates | Aer no fusion | Aer built-in | QuEST no fusion | QuEST measured-cost | QuEST measured-cost vs Aer built-in | noise Aer / QuEST |
|---:|---:|---:|---:|---:|---:|---:|---|
| 1000 | 994 | 15.01 | 10.01 | 12.23 | 3.32 | 3.01× | +1.0% / -0.2% |
| 1234 | 1236 | 19.50 | 12.16 | 15.30 | 4.09 | 2.97× | -0.2% / +0.1% |
| 2000 | 753 | 12.94 | 3.49 | 9.81 | 1.23 | 2.82× | +1.2% / +0.8% |
| 3000 | 1005 | 15.26 | 11.39 | 12.58 | 3.75 | 3.03× | +0.4% / -0.6% |
| 4000 | 1352 | 20.87 | 14.81 | 16.52 | 4.84 | 3.06× | -0.1% / +0.7% |
| 5000 | 708 | 12.05 | 3.21 | 9.13 | 1.10 | 2.93× | +0.0% / -0.0% |
| 6000 | 1030 | 16.14 | 9.56 | 12.97 | 3.26 | 2.93× | -0.2% / -0.1% |
