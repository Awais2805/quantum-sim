// quest_runner: execute .qops gate lists (written by quest_ops.py) on QuEST v4 and time them.
//
// .qops v1 (little-endian):
//   "QOPS" | u32 version=1 | u32 n | u32 num_ops
//   per op: u8 opcode | u8 k | k x u32 qubits | u8 nparams | nparams x f64 | payload
//   payload: DENSE -> 4^k x (f64 re, f64 im) row-major;  DIAG -> 2^k x (f64 re, f64 im)
// Qubits follow Qiskit qargs order; for DENSE/DIAG qubits[0] is the least significant bit
// of the matrix index. Controlled ops are [control, target].
//
// Usage: quest_runner [--reps R] [--warmup 0|1] [--verify prep.qops outdir] plan1.qops [...]
//   timing (R > 0): every plan starts from initPlusState; only the gate loop is timed;
//                   prints RESULT,<plan>,<rep>,<seconds>. Plans run round-robin with a
//                   rotating start, after one untimed warm-up each unless --warmup 0
//                   (warm-up runs with validation on; timed reps with setValidationOff()).
//   verify:         initZeroState -> prep -> plan; amplitudes written to outdir/<plan>.amps
//                   (2^n complex128). Use --reps 0 for verify only.
// Threads: OMP_NUM_THREADS (the Qureg is always created multithreaded).

#include "quest.h"

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <omp.h>

enum Opcode : uint8_t {
    OP_H = 0, OP_X, OP_Y, OP_Z, OP_S, OP_T, OP_PHASE, OP_RX, OP_RY, OP_RZ,
    OP_CX, OP_CY, OP_CZ, OP_CRX, OP_CRY, OP_CRZ, OP_CP, OP_SWAP, OP_DENSE, OP_DIAG,
    OP_COUNT
};

struct Instr {
    uint8_t op = 0;
    std::vector<int> q;
    std::vector<double> p;
    // prebuilt matrices (only the one matching op/k is used)
    CompMatr1 m1{};
    CompMatr2 m2{};
    CompMatr mk{};
    DiagMatr1 d1{};
    DiagMatr2 d2{};
    DiagMatr dk{};
    bool heap = false;  // mk or dk allocated
};

struct Plan {
    std::string path;
    int n = 0;
    std::vector<Instr> ops;
};

template <typename T>
static T readPod(std::ifstream& f, const std::string& path) {
    T v;
    if (!f.read(reinterpret_cast<char*>(&v), sizeof(T)))
        throw std::runtime_error("truncated file: " + path);
    return v;
}

static std::vector<qcomp> readComplex(std::ifstream& f, size_t count, const std::string& path) {
    std::vector<double> raw(2 * count);
    if (!f.read(reinterpret_cast<char*>(raw.data()), raw.size() * sizeof(double)))
        throw std::runtime_error("truncated matrix payload: " + path);
    std::vector<qcomp> out(count);
    for (size_t i = 0; i < count; i++)
        out[i] = qcomp(raw[2 * i], raw[2 * i + 1]);
    return out;
}

static Plan loadPlan(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("cannot open " + path);
    char magic[4];
    if (!f.read(magic, 4) || std::memcmp(magic, "QOPS", 4) != 0)
        throw std::runtime_error("not a .qops file: " + path);
    uint32_t version = readPod<uint32_t>(f, path);
    if (version != 1) throw std::runtime_error("unsupported .qops version in " + path);

    Plan plan;
    plan.path = path;
    plan.n = (int) readPod<uint32_t>(f, path);
    uint32_t numOps = readPod<uint32_t>(f, path);
    plan.ops.reserve(numOps);

    for (uint32_t i = 0; i < numOps; i++) {
        Instr in;
        in.op = readPod<uint8_t>(f, path);
        if (in.op >= OP_COUNT) throw std::runtime_error("bad opcode in " + path);
        int k = readPod<uint8_t>(f, path);
        in.q.resize(k);
        for (int j = 0; j < k; j++) {
            in.q[j] = (int) readPod<uint32_t>(f, path);
            if (in.q[j] >= plan.n) throw std::runtime_error("qubit out of range in " + path);
        }
        int np = readPod<uint8_t>(f, path);
        in.p.resize(np);
        for (int j = 0; j < np; j++) in.p[j] = readPod<double>(f, path);

        if (in.op == OP_DENSE) {
            size_t dim = size_t(1) << k;
            auto flat = readComplex(f, dim * dim, path);
            std::vector<std::vector<qcomp>> rows(dim, std::vector<qcomp>(dim));
            for (size_t r = 0; r < dim; r++)
                for (size_t c = 0; c < dim; c++) rows[r][c] = flat[r * dim + c];
            if (k == 1) in.m1 = getCompMatr1(rows);
            else if (k == 2) in.m2 = getCompMatr2(rows);
            else { in.mk = createCompMatr(k); setCompMatr(in.mk, rows); in.heap = true; }
        } else if (in.op == OP_DIAG) {
            auto diag = readComplex(f, size_t(1) << k, path);
            if (k == 1) in.d1 = getDiagMatr1(diag);
            else if (k == 2) in.d2 = getDiagMatr2(diag);
            else { in.dk = createDiagMatr(k); setDiagMatr(in.dk, diag); in.heap = true; }
        }
        plan.ops.push_back(std::move(in));
    }
    return plan;
}

static void freePlan(Plan& plan) {
    for (auto& in : plan.ops) {
        if (!in.heap) continue;
        if (in.op == OP_DENSE) destroyCompMatr(in.mk);
        else destroyDiagMatr(in.dk);
    }
}

static inline void apply(Qureg qureg, Instr& in) {
    int* t = in.q.data();
    switch (in.op) {
        case OP_H:     applyHadamard(qureg, t[0]); break;
        case OP_X:     applyPauliX(qureg, t[0]); break;
        case OP_Y:     applyPauliY(qureg, t[0]); break;
        case OP_Z:     applyPauliZ(qureg, t[0]); break;
        case OP_S:     applyS(qureg, t[0]); break;
        case OP_T:     applyT(qureg, t[0]); break;
        case OP_PHASE: applyPhaseShift(qureg, t[0], in.p[0]); break;
        case OP_RX:    applyRotateX(qureg, t[0], in.p[0]); break;
        case OP_RY:    applyRotateY(qureg, t[0], in.p[0]); break;
        case OP_RZ:    applyRotateZ(qureg, t[0], in.p[0]); break;
        case OP_CX:    applyControlledPauliX(qureg, t[0], t[1]); break;
        case OP_CY:    applyControlledPauliY(qureg, t[0], t[1]); break;
        case OP_CZ:    applyControlledPauliZ(qureg, t[0], t[1]); break;
        case OP_CRX:   applyControlledRotateX(qureg, t[0], t[1], in.p[0]); break;
        case OP_CRY:   applyControlledRotateY(qureg, t[0], t[1], in.p[0]); break;
        case OP_CRZ:   applyControlledRotateZ(qureg, t[0], t[1], in.p[0]); break;
        case OP_CP:    applyTwoQubitPhaseShift(qureg, t[0], t[1], in.p[0]); break;
        case OP_SWAP:  applySwap(qureg, t[0], t[1]); break;
        case OP_DENSE: {
            int k = (int) in.q.size();
            if (k == 1) applyCompMatr1(qureg, t[0], in.m1);
            else if (k == 2) applyCompMatr2(qureg, t[0], t[1], in.m2);
            else applyCompMatr(qureg, t, k, in.mk);
            break;
        }
        case OP_DIAG: {
            int k = (int) in.q.size();
            if (k == 1) applyDiagMatr1(qureg, t[0], in.d1);
            else if (k == 2) applyDiagMatr2(qureg, t[0], t[1], in.d2);
            else applyDiagMatr(qureg, t, k, in.dk);
            break;
        }
    }
}

static void run(Qureg qureg, Plan& plan) {
    for (auto& in : plan.ops) apply(qureg, in);
}

int main(int argc, char** argv) {
    int reps = 3;
    int warmup = 1;
    std::string prepPath, outDir;
    std::vector<std::string> planPaths;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a == "--reps" && i + 1 < argc) reps = std::stoi(argv[++i]);
        else if (a == "--warmup" && i + 1 < argc) warmup = std::stoi(argv[++i]);
        else if (a == "--verify" && i + 2 < argc) { prepPath = argv[++i]; outDir = argv[++i]; }
        else if (a.rfind("--", 0) == 0) { std::fprintf(stderr, "unknown option %s\n", a.c_str()); return 2; }
        else planPaths.push_back(a);
    }
    if (planPaths.empty()) {
        std::fprintf(stderr, "usage: quest_runner [--reps R] [--verify prep.qops outdir] plan.qops...\n");
        return 2;
    }

    initQuESTEnv();
    std::vector<Plan> plans;
    try {
        for (auto& p : planPaths) plans.push_back(loadPlan(p));
    } catch (const std::exception& e) {
        std::fprintf(stderr, "error: %s\n", e.what());
        finalizeQuESTEnv();
        return 1;
    }
    int n = plans[0].n;
    for (auto& p : plans)
        if (p.n != n) { std::fprintf(stderr, "error: plans differ in qubit count\n"); return 1; }

    Qureg qureg = createCustomQureg(n, /*isDensMatr*/ 0, /*useDistrib*/ 0, /*useGpuAccel*/ 0, /*useMultithread*/ 1);
    std::printf("INFO,n=%d,plans=%zu,omp_threads=%d,multithreaded=%d\n",
                n, plans.size(), omp_get_max_threads(), qureg.isMultithreaded);

    if (!prepPath.empty()) {
        Plan prep = loadPlan(prepPath);
        if (prep.n != n) { std::fprintf(stderr, "error: prep qubit count differs\n"); return 1; }
        std::vector<qcomp> amps(size_t(1) << n);
        for (size_t i = 0; i < plans.size(); i++) {
            initZeroState(qureg);
            run(qureg, prep);
            run(qureg, plans[i]);
            getQuregAmps(amps.data(), qureg, 0, (qindex) amps.size());
            std::string out = outDir + "/" + std::to_string(i) + ".amps";
            std::ofstream f(out, std::ios::binary);
            f.write(reinterpret_cast<const char*>(amps.data()), amps.size() * sizeof(qcomp));
            if (!f) { std::fprintf(stderr, "error: cannot write %s\n", out.c_str()); return 1; }
        }
        freePlan(prep);
        std::printf("VERIFY_WRITTEN,%zu\n", plans.size());
    }

    if (reps > 0) {
        if (warmup)  // untimed warm-up; runs with validation on (checks + caches unitarity)
            for (auto& p : plans) { initPlusState(qureg); run(qureg, p); }
        setValidationOff();
        size_t P = plans.size();
        for (int r = 0; r < reps; r++) {
            for (size_t j = 0; j < P; j++) {
                size_t i = (j + r) % P;
                initPlusState(qureg);
                auto t0 = std::chrono::steady_clock::now();
                run(qureg, plans[i]);
                auto t1 = std::chrono::steady_clock::now();
                std::printf("RESULT,%zu,%d,%.9f\n", i, r, std::chrono::duration<double>(t1 - t0).count());
                std::fflush(stdout);
            }
        }
    }

    for (auto& p : plans) freePlan(p);
    destroyQureg(qureg);
    finalizeQuESTEnv();
    return 0;
}
