#!/usr/bin/env bash
# Build QuEST (Linux, Release, OpenMP, -march=native) in a private folder and compile
# quest_runner against it. QuEST's own source tree and its existing build/ are untouched.
#
# Usage: ./build_quest.sh [path/to/QuEST]          (default: ../../QuEST relative to this script)
# Result: build/quest-linux/quest_runner
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUEST_SRC="$(cd "${1:-$HERE/../../QuEST}" && pwd)"
BUILD="$HERE/build/quest-linux"
JOBS="$(nproc 2>/dev/null || echo 4)"

echo "QuEST source: $QUEST_SRC"
echo "Build dir:    $BUILD"

if [ ! -f "$BUILD/libQuEST.so" ] && ! ls "$BUILD"/libQuEST*.so >/dev/null 2>&1; then
    cmake -S "$QUEST_SRC" -B "$BUILD" \
        -DCMAKE_BUILD_TYPE=Release \
        -DENABLE_MULTITHREADING=ON \
        -DENABLE_TESTING=OFF \
        -DCMAKE_CXX_FLAGS="-march=native" \
        -DCMAKE_C_FLAGS="-march=native"
    cmake --build "$BUILD" -j "$JOBS"
fi

LIB_DIR="$(dirname "$(ls "$BUILD"/libQuEST*.so | head -1)")"
g++ -O3 -march=native -std=c++17 -fopenmp \
    -I "$QUEST_SRC/quest/include" -I "$BUILD/quest/include" -I "$QUEST_SRC" -I "$BUILD" \
    "$HERE/quest_runner.cpp" -o "$BUILD/quest_runner" \
    -L "$LIB_DIR" -lQuEST -Wl,-rpath,"$LIB_DIR"

echo "built $BUILD/quest_runner"
