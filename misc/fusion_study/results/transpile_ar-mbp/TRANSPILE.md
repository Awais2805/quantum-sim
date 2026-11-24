# Fusion-pass time only (no simulation)

Machine: `ar-mbp` (Intel(R) Core(TM) i5-8257U CPU @ 1.40GHz), single Python process. Time = fastest of 3 repeats, averaged over rqc seeds 1234, 1000, 2000. Cost table: `cost_table_v2_qbench_quest_t2_n24.json` (QuEST, measured on qbench; used only to decide what to fuse).

## QFT

| method | k | n=16 | n=20 | n=24 | n=26 | n=28 | n=30 | n=32 | n=34 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| *gates in circuit* | | 144 | 220 | 312 | 364 | 420 | 480 | 544 | 612 |
| horizontal, greedy | 2 | 0.008 s | 0.011 s | 0.015 s | 0.017 s | 0.018 s | 0.021 s | 0.024 s | 0.023 s |
| horizontal, cost model | 2 | 0.013 s | 0.018 s | 0.023 s | 0.025 s | 0.028 s | 0.030 s | 0.035 s | 0.033 s |
| horizontal, greedy | 3 | 0.025 s | 0.039 s | 0.058 s | 0.067 s | 0.079 s | 0.089 s | 0.109 s | 0.107 s |
| horizontal, cost model | 3 | 0.039 s | 0.061 s | 0.082 s | 0.094 s | 0.107 s | 0.123 s | 0.137 s | 0.145 s |
| horizontal, greedy | 4 | 0.023 s | 0.036 s | 0.055 s | 0.061 s | 0.074 s | 0.080 s | 0.090 s | 0.100 s |
| horizontal, cost model | 4 | 0.063 s | 0.094 s | 0.136 s | 0.154 s | 0.185 s | 0.207 s | 0.223 s | 0.247 s |
| vertical, greedy | 2 | 0.003 s | 0.004 s | 0.005 s | 0.007 s | 0.008 s | 0.008 s | 0.009 s | 0.010 s |
| vertical, cost model | 2 | 0.003 s | 0.004 s | 0.006 s | 0.007 s | 0.008 s | 0.008 s | 0.009 s | 0.010 s |
| vertical, greedy | 3 | 0.008 s | 0.010 s | 0.013 s | 0.015 s | 0.017 s | 0.017 s | 0.018 s | 0.020 s |
| vertical, cost model | 3 | 0.010 s | 0.015 s | 0.019 s | 0.022 s | 0.025 s | 0.026 s | 0.028 s | 0.031 s |
| vertical, greedy | 4 | 0.028 s | 0.042 s | 0.061 s | 0.070 s | 0.085 s | 0.093 s | 0.100 s | 0.121 s |
| vertical, cost model | 4 | 0.038 s | 0.058 s | 0.083 s | 0.093 s | 0.108 s | 0.129 s | 0.131 s | 0.148 s |
| measured-cost fusion | – | 0.016 s | 0.025 s | 0.038 s | 0.044 s | 0.052 s | 0.062 s | 0.067 s | 0.076 s |

## RQC

| method | k | n=16 | n=20 | n=24 | n=26 | n=28 | n=30 | n=32 | n=34 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| *gates in circuit* | | 472 | 641 | 994 | 1372 | 1251 | 1327 | 1884 | 1704 |
| horizontal, greedy | 2 | 0.051 s | 0.065 s | 0.096 s | 0.142 s | 0.131 s | 0.126 s | 0.197 s | 0.158 s |
| horizontal, cost model | 2 | 0.096 s | 0.122 s | 0.192 s | 0.272 s | 0.242 s | 0.243 s | 0.377 s | 0.295 s |
| horizontal, greedy | 3 | 0.044 s | 0.062 s | 0.102 s | 0.133 s | 0.110 s | 0.113 s | 0.175 s | 0.141 s |
| horizontal, cost model | 3 | 0.097 s | 0.122 s | 0.220 s | 0.286 s | 0.236 s | 0.236 s | 0.372 s | 0.303 s |
| horizontal, greedy | 4 | 0.043 s | 0.058 s | 0.098 s | 0.129 s | 0.117 s | 0.115 s | 0.172 s | 0.147 s |
| horizontal, cost model | 4 | 0.109 s | 0.128 s | 0.219 s | 0.308 s | 0.246 s | 0.241 s | 0.399 s | 0.329 s |
| vertical, greedy | 2 | 0.045 s | 0.074 s | 0.115 s | 0.148 s | 0.155 s | 0.168 s | 0.213 s | 0.210 s |
| vertical, cost model | 2 | 0.092 s | 0.144 s | 0.221 s | 0.292 s | 0.328 s | 0.364 s | 0.427 s | 0.423 s |
| vertical, greedy | 3 | 0.065 s | 0.092 s | 0.144 s | 0.205 s | 0.186 s | 0.218 s | 0.281 s | 0.245 s |
| vertical, cost model | 3 | 0.149 s | 0.216 s | 0.338 s | 0.446 s | 0.450 s | 0.542 s | 0.655 s | 0.616 s |
| vertical, greedy | 4 | 0.066 s | 0.089 s | 0.143 s | 0.194 s | 0.173 s | 0.210 s | 0.276 s | 0.231 s |
| vertical, cost model | 4 | 0.193 s | 0.274 s | 0.443 s | 0.586 s | 0.562 s | 0.620 s | 0.844 s | 0.778 s |
| measured-cost fusion | – | 0.047 s | 0.060 s | 0.100 s | 0.147 s | 0.123 s | 0.131 s | 0.205 s | 0.158 s |
