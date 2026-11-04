/*
Gate fusion experiment on QuEST (v4.2).

Approach: build a random circuit of 1- and 2-qubit gates, then
  (A) run it unfused, one named QuEST call per gate (stock behavior),
  (B) fuse it greedily into blocks of <= 2 qubits, and run each block with
      the cheapest matching QuEST call:
        diagonal 1q -> applyDiagMatr1    dense 1q -> applyCompMatr1
        diagonal 2q -> applyDiagMatr2    dense 2q -> applyCompMatr2
Both start from the same random state. Correctness check: fidelity(A, B) ~ 1.
Also reports the number of statevector passes (QuEST calls) and wall time.

Fusion rule (greedy, conservative):
  - keep "open" blocks with disjoint qubit sets (gates on disjoint qubits commute,
    so open blocks can be emitted in any order relative to each other)
  - a new gate on qubits Q: collect the open blocks that touch Q;
      if (their qubits + Q) fit in 2 qubits -> merge them and absorb the gate
      else -> emit those blocks, start a new block holding just the gate
  - at the end, emit all open blocks

Matrix convention: a block on qubits (q[0], q[1]) uses basis index
  i = bit(q[0]) + 2*bit(q[1]), i.e. q[0] is least significant. This matches
  applyCompMatr2(qureg, target1, target2, M), which treats target1 as least significant.
Gate order: if gate G comes after the block, the block becomes G * M (G on the left).

Usage: fuser <numQubits> <numGates> [seed] [reps]
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <complex.h>
#include <time.h>
#include "quest.h"

#define MAX_BLOCK_QUBITS 2
#define DIM 4               /* 2^MAX_BLOCK_QUBITS */
#define EPS 1e-12

/* ---------- circuit ---------- */

typedef enum { G_H, G_X, G_Z, G_S, G_T, G_RX, G_RZ, G_CNOT, G_CZ, G_NUM } GateType;
static const char* GATE_NAME[] = {"H", "X", "Z", "S", "T", "RX", "RZ", "CNOT", "CZ"};

typedef struct {
    GateType type;
    int nq;          /* 1 or 2 */
    int q[2];        /* for CNOT: q[0] = control, q[1] = target */
    double angle;
} Gate;

static int isTwoQubit(GateType t) { return t == G_CNOT || t == G_CZ; }

/* gate matrix on its own qubits, index = bit(q[0]) + 2*bit(q[1]) */
static void gateMatrix(const Gate* g, qcomp m[DIM][DIM]) {
    memset(m, 0, sizeof(qcomp) * DIM * DIM);
    const double r = 1.0 / sqrt(2.0);
    const double h = g->angle / 2.0;
    switch (g->type) {
        case G_H:  m[0][0] = r; m[0][1] = r; m[1][0] = r; m[1][1] = -r; break;
        case G_X:  m[0][1] = 1; m[1][0] = 1; break;
        case G_Z:  m[0][0] = 1; m[1][1] = -1; break;
        case G_S:  m[0][0] = 1; m[1][1] = I; break;
        case G_T:  m[0][0] = 1; m[1][1] = cexp(I * M_PI / 4); break;
        /* QuEST: RX(a) = exp(-i a X / 2), RZ(a) = exp(-i a Z / 2) */
        case G_RX: m[0][0] = cos(h); m[0][1] = -I * sin(h);
                   m[1][0] = -I * sin(h); m[1][1] = cos(h); break;
        case G_RZ: m[0][0] = cexp(-I * h); m[1][1] = cexp(I * h); break;
        /* control = bit 0, target = bit 1: swap |c=1,t=0> (1) with |c=1,t=1> (3) */
        case G_CNOT: m[0][0] = 1; m[2][2] = 1; m[1][3] = 1; m[3][1] = 1; break;
        case G_CZ:   m[0][0] = 1; m[1][1] = 1; m[2][2] = 1; m[3][3] = -1; break;
        default: break;
    }
}

static void runUnfusedGate(Qureg qr, const Gate* g) {
    switch (g->type) {
        case G_H:    applyHadamard(qr, g->q[0]); break;
        case G_X:    applyPauliX(qr, g->q[0]); break;
        case G_Z:    applyPauliZ(qr, g->q[0]); break;
        case G_S:    applyS(qr, g->q[0]); break;
        case G_T:    applyT(qr, g->q[0]); break;
        case G_RX:   applyRotateX(qr, g->q[0], g->angle); break;
        case G_RZ:   applyRotateZ(qr, g->q[0], g->angle); break;
        case G_CNOT: applyControlledPauliX(qr, g->q[0], g->q[1]); break;
        case G_CZ:   applyControlledPauliZ(qr, g->q[0], g->q[1]); break;
        default: break;
    }
}

static void randomCircuit(Gate* gates, int numGates, int numQubits) {
    for (int i = 0; i < numGates; i++) {
        Gate* g = &gates[i];
        g->type = (GateType)(rand() % G_NUM);
        if (numQubits < 2 && isTwoQubit(g->type)) g->type = G_H;
        g->nq = isTwoQubit(g->type) ? 2 : 1;
        g->q[0] = rand() % numQubits;
        if (g->nq == 2) {
            do { g->q[1] = rand() % numQubits; } while (g->q[1] == g->q[0]);
        }
        g->angle = 2 * M_PI * rand() / (double)RAND_MAX;
    }
}

/* ---------- fused blocks ---------- */

typedef struct {
    int nq;               /* 1 or 2 */
    int q[2];             /* q[0] least significant */
    qcomp m[DIM][DIM];    /* top-left 2^nq x 2^nq used */
    int numGates;         /* gates absorbed, for reporting */
} Block;

/*
Embed a matrix acting on qubits `sub` (k of them) into the block basis on qubits `blk`
(n of them, every sub qubit must be in blk). Result entry (i, j) is
  sub-matrix[sub bits of i][sub bits of j] if the non-sub bits of i and j agree, else 0.
*/
static void embed(qcomp in[DIM][DIM], const int* sub, int k,
                  const int* blk, int n, qcomp out[DIM][DIM]) {
    int pos[MAX_BLOCK_QUBITS];          /* position of sub[s] inside blk */
    int subMask = 0;
    for (int s = 0; s < k; s++) {
        for (int b = 0; b < n; b++) if (blk[b] == sub[s]) pos[s] = b;
        subMask |= 1 << pos[s];
    }
    int dim = 1 << n;
    memset(out, 0, sizeof(qcomp) * DIM * DIM);
    for (int i = 0; i < dim; i++)
        for (int j = 0; j < dim; j++) {
            if ((i & ~subMask) != (j & ~subMask)) continue;
            int si = 0, sj = 0;
            for (int s = 0; s < k; s++) {
                si |= ((i >> pos[s]) & 1) << s;
                sj |= ((j >> pos[s]) & 1) << s;
            }
            out[i][j] = in[si][sj];
        }
}

/* c = a * b (DIM x DIM) */
static void matmul(qcomp a[DIM][DIM], qcomp b[DIM][DIM], qcomp c[DIM][DIM]) {
    qcomp t[DIM][DIM];
    for (int i = 0; i < DIM; i++)
        for (int j = 0; j < DIM; j++) {
            qcomp s = 0;
            for (int x = 0; x < DIM; x++) s += a[i][x] * b[x][j];
            t[i][j] = s;
        }
    memcpy(c, t, sizeof t);
}

static int blockIsDiagonal(Block* b) {
    int dim = 1 << b->nq;
    for (int i = 0; i < dim; i++)
        for (int j = 0; j < dim; j++)
            if (i != j && cabs(b->m[i][j]) > EPS) return 0;
    return 1;
}

/* re-express block b on a (larger) qubit list `qs` of length n */
static void widenBlock(Block* b, const int* qs, int n) {
    qcomp out[DIM][DIM];
    embed(b->m, b->q, b->nq, qs, n, out);
    memcpy(b->m, out, sizeof out);
    b->nq = n;
    for (int i = 0; i < n; i++) b->q[i] = qs[i];
}

/* ---------- emitted plan ---------- */

typedef enum { K_DIAG1, K_COMP1, K_DIAG2, K_COMP2 } Kind;
static const char* KIND_NAME[] = {"applyDiagMatr1", "applyCompMatr1",
                                  "applyDiagMatr2", "applyCompMatr2"};

typedef struct {
    Kind kind;
    int q[2];
    int numGates;
    CompMatr1 c1; CompMatr2 c2; DiagMatr1 d1; DiagMatr2 d2;
} FusedOp;

static void emit(Block* b, FusedOp* ops, int* numOps) {
    FusedOp* op = &ops[(*numOps)++];
    op->q[0] = b->q[0]; op->q[1] = b->q[1];
    op->numGates = b->numGates;
    int diag = blockIsDiagonal(b);
    if (b->nq == 1) {
        if (diag) {
            qcomp d[2] = {b->m[0][0], b->m[1][1]};
            op->kind = K_DIAG1; op->d1 = getDiagMatr1(d);
        } else {
            qcomp r0[2] = {b->m[0][0], b->m[0][1]}, r1[2] = {b->m[1][0], b->m[1][1]};
            qcomp* rows[2] = {r0, r1};
            op->kind = K_COMP1; op->c1 = getCompMatr1(rows);
        }
    } else {
        if (diag) {
            qcomp d[4] = {b->m[0][0], b->m[1][1], b->m[2][2], b->m[3][3]};
            op->kind = K_DIAG2; op->d2 = getDiagMatr2(d);
        } else {
            qcomp* rows[4] = {(qcomp*)b->m[0], (qcomp*)b->m[1], (qcomp*)b->m[2], (qcomp*)b->m[3]};
            op->kind = K_COMP2; op->c2 = getCompMatr2(rows);
        }
    }
}

static void runFusedOp(Qureg qr, const FusedOp* op) {
    switch (op->kind) {
        case K_DIAG1: applyDiagMatr1(qr, op->q[0], op->d1); break;
        case K_COMP1: applyCompMatr1(qr, op->q[0], op->c1); break;
        case K_DIAG2: applyDiagMatr2(qr, op->q[0], op->q[1], op->d2); break;
        case K_COMP2: applyCompMatr2(qr, op->q[0], op->q[1], op->c2); break;
    }
}

/* greedy fusion: gates -> ops; returns number of ops */
static int fuse(const Gate* gates, int numGates, int numQubits, FusedOp* ops) {
    Block* blocks = calloc(numQubits, sizeof(Block));   /* at most one open block per qubit */
    int* owner = malloc(numQubits * sizeof(int));       /* qubit -> open block index, or -1 */
    int* isOpen = calloc(numQubits, sizeof(int));
    for (int i = 0; i < numQubits; i++) owner[i] = -1;
    int numOps = 0;

    for (int g = 0; g < numGates; g++) {
        const Gate* gate = &gates[g];

        /* open blocks touching this gate, and the union of their qubits with the gate's */
        int touch[2], nt = 0, uq[2 * MAX_BLOCK_QUBITS + 2], nu = 0;
        for (int s = 0; s < gate->nq; s++) {
            int bi = owner[gate->q[s]];
            if (bi >= 0 && !(nt == 1 && touch[0] == bi)) touch[nt++] = bi;
        }
        for (int t = 0; t < nt; t++)
            for (int s = 0; s < blocks[touch[t]].nq; s++) uq[nu++] = blocks[touch[t]].q[s];
        for (int s = 0; s < gate->nq; s++) {
            int seen = 0;
            for (int u = 0; u < nu; u++) if (uq[u] == gate->q[s]) seen = 1;
            if (!seen) uq[nu++] = gate->q[s];
        }

        int target;   /* block that will absorb the gate */
        if (nu <= MAX_BLOCK_QUBITS) {
            /* merge touching blocks (if any) into one block on qubits uq */
            target = (nt > 0) ? touch[0] : -1;
            if (target < 0) {
                for (int i = 0; i < numQubits; i++) if (!isOpen[i]) { target = i; break; }
                Block* b = &blocks[target];
                isOpen[target] = 1;
                b->nq = 1; b->q[0] = uq[0]; b->numGates = 0;
                memset(b->m, 0, sizeof b->m);
                b->m[0][0] = 1; b->m[1][1] = 1;
            }
            widenBlock(&blocks[target], uq, nu);
            if (nt == 2) {
                /* second block is on disjoint qubits: tensor it in */
                Block* o = &blocks[touch[1]];
                qcomp e[DIM][DIM];
                embed(o->m, o->q, o->nq, uq, nu, e);
                matmul(e, blocks[target].m, blocks[target].m);
                blocks[target].numGates += o->numGates;
                isOpen[touch[1]] = 0;
            }
        } else {
            /* does not fit: emit touching blocks, start a fresh block for the gate */
            for (int t = 0; t < nt; t++) {
                Block* b = &blocks[touch[t]];
                emit(b, ops, &numOps);
                for (int s = 0; s < b->nq; s++) owner[b->q[s]] = -1;
                isOpen[touch[t]] = 0;
            }
            target = -1;
            for (int i = 0; i < numQubits; i++) if (!isOpen[i]) { target = i; break; }
            Block* b = &blocks[target];
            isOpen[target] = 1;
            b->nq = gate->nq; b->numGates = 0;
            for (int s = 0; s < gate->nq; s++) b->q[s] = gate->q[s];
            memset(b->m, 0, sizeof b->m);
            for (int i = 0; i < (1 << b->nq); i++) b->m[i][i] = 1;
        }

        /* absorb: block = G * block */
        Block* b = &blocks[target];
        qcomp gm[DIM][DIM], e[DIM][DIM];
        gateMatrix(gate, gm);
        embed(gm, gate->q, gate->nq, b->q, b->nq, e);
        matmul(e, b->m, b->m);
        b->numGates++;
        for (int s = 0; s < b->nq; s++) owner[b->q[s]] = target;
    }

    for (int i = 0; i < numQubits; i++) if (isOpen[i]) emit(&blocks[i], ops, &numOps);

    free(blocks); free(owner); free(isOpen);
    return numOps;
}

/* ---------- main ---------- */

static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + 1e-9 * t.tv_nsec;
}

int main(int argc, char** argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: %s <numQubits> <numGates> [seed] [reps]\n", argv[0]);
        return 1;
    }
    int numQubits = atoi(argv[1]);
    int numGates = atoi(argv[2]);
    unsigned seed = (argc > 3) ? (unsigned)atoi(argv[3]) : 1234u;
    int reps = (argc > 4) ? atoi(argv[4]) : 5;

    initQuESTEnv();
    setSeeds(&seed, 1);
    srand(seed);

    Gate* gates = malloc(numGates * sizeof(Gate));
    FusedOp* ops = malloc(numGates * sizeof(FusedOp));
    randomCircuit(gates, numGates, numQubits);

    int numOps = fuse(gates, numGates, numQubits, ops);

    int kindCount[4] = {0};
    for (int i = 0; i < numOps; i++) kindCount[ops[i].kind]++;

    Qureg init = createQureg(numQubits);
    Qureg a = createQureg(numQubits);
    Qureg b = createQureg(numQubits);
    initRandomPureState(init);

    /* warm-up (threads, page faults), then best of `reps` runs each, both from the same state */
    setQuregToClone(a, init);
    for (int i = 0; i < numOps; i++) runFusedOp(a, &ops[i]);
    double tUnfused = 1e30, tFused = 1e30;
    for (int r = 0; r < reps; r++) {
        setQuregToClone(a, init);
        double t0 = now();
        for (int i = 0; i < numGates; i++) runUnfusedGate(a, &gates[i]);
        double t1 = now();
        setQuregToClone(b, init);
        double t2 = now();
        for (int i = 0; i < numOps; i++) runFusedOp(b, &ops[i]);
        double t3 = now();
        if (t1 - t0 < tUnfused) tUnfused = t1 - t0;
        if (t3 - t2 < tFused) tFused = t3 - t2;
    }

    qreal fid = calcFidelity(a, b);

    printf("qubits=%d gates=%d seed=%u\n", numQubits, numGates, seed);
    printf("unfused: %d QuEST calls, %.4f s (best of %d)\n", numGates, tUnfused, reps);
    printf("fused:   %d QuEST calls, %.4f s  (", numOps, tFused);
    for (int k = 0; k < 4; k++) printf("%s%s=%d", k ? ", " : "", KIND_NAME[k], kindCount[k]);
    printf(")\n");
    printf("speedup: %.2fx   fidelity(unfused, fused) = %.12f\n", tUnfused / tFused, fid);

    if (numQubits <= 4 && numGates <= 20) {
        printf("\ncircuit:\n");
        for (int i = 0; i < numGates; i++) {
            printf("  %-4s q%d", GATE_NAME[gates[i].type], gates[i].q[0]);
            if (gates[i].nq == 2) printf(",q%d", gates[i].q[1]);
            printf("\n");
        }
        printf("fused plan:\n");
        for (int i = 0; i < numOps; i++) {
            printf("  %s q%d", KIND_NAME[ops[i].kind], ops[i].q[0]);
            if (ops[i].kind >= K_DIAG2) printf(",q%d", ops[i].q[1]);
            printf("   (%d gates)\n", ops[i].numGates);
        }
    }

    int ok = fabs(fid - 1.0) < 1e-9;
    printf("%s\n", ok ? "PASS" : "FAIL");

    destroyQureg(init); destroyQureg(a); destroyQureg(b);
    free(gates); free(ops);
    finalizeQuESTEnv();
    return ok ? 0 : 2;
}
