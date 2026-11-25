/**
 * OpenMP scientific kernels for the hybrid desktop grid.
 * Modes: heat2d | batch | irregular | selftest
 *
 * Usage:
 *   omp_kernels heat2d --grid 128 --steps 40 --tile 16 --start-row 0 --rows 32
 *   omp_kernels batch  --offset 0 --count 8 --length 100000
 *   omp_kernels irregular --seed 7 --work 20000
 *   omp_kernels selftest
 */
#include <omp.h>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

struct Args {
  std::string mode = "selftest";
  int grid = 128;
  int steps = 40;
  int tile = 16;
  int start_row = 0;
  int rows = -1;
  int offset = 0;
  int count = 8;
  int length = 100000;
  int seed = 1;
  long long work = 20000;
  int threads = 0;  // 0 = default
};

static int parse_int(const char* s, int fallback) {
  if (!s) return fallback;
  return static_cast<int>(std::strtol(s, nullptr, 10));
}

static long long parse_ll(const char* s, long long fallback) {
  if (!s) return fallback;
  return std::strtoll(s, nullptr, 10);
}

static Args parse_args(int argc, char** argv) {
  Args a;
  if (argc >= 2) a.mode = argv[1];
  for (int i = 2; i < argc; ++i) {
    std::string k = argv[i];
    const char* v = (i + 1 < argc) ? argv[i + 1] : nullptr;
    if (k == "--grid" && v) { a.grid = parse_int(v, a.grid); ++i; }
    else if (k == "--steps" && v) { a.steps = parse_int(v, a.steps); ++i; }
    else if (k == "--tile" && v) { a.tile = parse_int(v, a.tile); ++i; }
    else if (k == "--start-row" && v) { a.start_row = parse_int(v, a.start_row); ++i; }
    else if (k == "--rows" && v) { a.rows = parse_int(v, a.rows); ++i; }
    else if (k == "--offset" && v) { a.offset = parse_int(v, a.offset); ++i; }
    else if (k == "--count" && v) { a.count = parse_int(v, a.count); ++i; }
    else if (k == "--length" && v) { a.length = parse_int(v, a.length); ++i; }
    else if (k == "--seed" && v) { a.seed = parse_int(v, a.seed); ++i; }
    else if (k == "--work" && v) { a.work = parse_ll(v, a.work); ++i; }
    else if (k == "--threads" && v) { a.threads = parse_int(v, a.threads); ++i; }
  }
  return a;
}

static double now_ms() {
  using clock = std::chrono::steady_clock;
  return std::chrono::duration<double, std::milli>(clock::now().time_since_epoch()).count();
}

/** Tiled 2D heat equation on a strip of rows (inclusive of halo handling). */
static int run_heat2d(const Args& a) {
  const int n = a.grid;
  int rows = a.rows < 0 ? n : a.rows;
  if (a.start_row < 0 || a.start_row + rows > n) {
    std::cerr << "invalid heat strip\n";
    return 2;
  }
  // Full grid locally for correctness of interior stencil on strip; only strip is "owned".
  std::vector<double> u(static_cast<size_t>(n) * n, 0.0);
  std::vector<double> v(static_cast<size_t>(n) * n, 0.0);
  for (int j = 0; j < n; ++j) {
    u[j] = 1.0;  // top boundary hot
    u[static_cast<size_t>(n - 1) * n + j] = 0.0;
  }
  for (int i = 0; i < n; ++i) {
    u[static_cast<size_t>(i) * n] = 0.0;
    u[static_cast<size_t>(i) * n + (n - 1)] = 0.0;
  }

  const double alpha = 0.1;
  const int r0 = a.start_row;
  const int r1 = a.start_row + rows;
  const int tile = std::max(1, a.tile);
  // Local hotspot inside owned strip so distributed strips remain meaningful
  {
    const int mid_i = std::min(n - 2, std::max(1, (r0 + r1) / 2));
    const int mid_j = n / 2;
    u[static_cast<size_t>(mid_i) * n + mid_j] = 5.0;
  }

  const double t0 = now_ms();
  for (int step = 0; step < a.steps; ++step) {
#pragma omp parallel for collapse(2) schedule(static)
    for (int ii = r0; ii < r1; ii += tile) {
      for (int jj = 0; jj < n; jj += tile) {
        const int i_end = std::min(ii + tile, r1);
        const int j_end = std::min(jj + tile, n);
        for (int i = ii; i < i_end; ++i) {
          if (i == 0 || i == n - 1) continue;
          for (int j = jj; j < j_end; ++j) {
            if (j == 0 || j == n - 1) continue;
            const size_t idx = static_cast<size_t>(i) * n + j;
            const double c = u[idx];
            const double up = u[idx - n];
            const double dn = u[idx + n];
            const double lf = u[idx - 1];
            const double rt = u[idx + 1];
            v[idx] = c + alpha * (up + dn + lf + rt - 4.0 * c);
          }
        }
      }
    }
#pragma omp parallel for
    for (int i = r0; i < r1; ++i) {
      for (int j = 0; j < n; ++j) {
        const size_t idx = static_cast<size_t>(i) * n + j;
        u[idx] = v[idx];
      }
    }
  }
  const double elapsed = now_ms() - t0;

  // Checksum over owned interior
  double checksum = 0.0;
  int cells = 0;
  for (int i = r0; i < r1; ++i) {
    for (int j = 0; j < n; ++j) {
      checksum += u[static_cast<size_t>(i) * n + j];
      ++cells;
    }
  }

  std::cout << std::setprecision(17)
            << "{\"kernel\":\"heat2d\",\"checksum\":" << checksum
            << ",\"cells\":" << cells
            << ",\"elapsed_ms\":" << elapsed
            << ",\"threads\":" << omp_get_max_threads()
            << ",\"start_row\":" << a.start_row
            << ",\"rows\":" << rows
            << ",\"grid\":" << n
            << ",\"steps\":" << a.steps
            << "}\n";
  return 0;
}

/** Embarrassingly parallel independent array reductions. */
static int run_batch(const Args& a) {
  const int count = std::max(1, a.count);
  const int length = std::max(1, a.length);
  std::vector<double> partial(static_cast<size_t>(count), 0.0);

  const double t0 = now_ms();
#pragma omp parallel for schedule(static)
  for (int k = 0; k < count; ++k) {
    const int id = a.offset + k;
    double s = 0.0;
    for (int i = 0; i < length; ++i) {
      // cheap deterministic work
      const double x = std::sin(0.001 * (id + 1) * (i + 1));
      s += x * x;
    }
    partial[static_cast<size_t>(k)] = s;
  }
  const double elapsed = now_ms() - t0;

  double checksum = 0.0;
  for (double p : partial) checksum += p;

  std::cout << std::setprecision(17)
            << "{\"kernel\":\"batch\",\"checksum\":" << checksum
            << ",\"count\":" << count
            << ",\"offset\":" << a.offset
            << ",\"length\":" << length
            << ",\"elapsed_ms\":" << elapsed
            << ",\"threads\":" << omp_get_max_threads()
            << "}\n";
  return 0;
}

/** Mildly irregular workload (variable inner loop) to study stragglers. */
static int run_irregular(const Args& a) {
  // Deterministic pseudo-random work from seed
  unsigned state = static_cast<unsigned>(a.seed) * 1664525u + 1013904223u;
  long long units = a.work + static_cast<long long>(state % 10000u);
  volatile double acc = 0.0;

  const double t0 = now_ms();
#pragma omp parallel
  {
    double local = 0.0;
#pragma omp for schedule(dynamic, 64)
    for (long long i = 0; i < units; ++i) {
      local += std::sin(0.0001 * static_cast<double>(i + a.seed));
    }
#pragma omp atomic
    acc += local;
  }
  const double elapsed = now_ms() - t0;

  std::cout << std::setprecision(17)
            << "{\"kernel\":\"irregular\",\"checksum\":" << static_cast<double>(acc)
            << ",\"work\":" << units
            << ",\"seed\":" << a.seed
            << ",\"elapsed_ms\":" << elapsed
            << ",\"threads\":" << omp_get_max_threads()
            << "}\n";
  return 0;
}

static int run_selftest() {
  Args heat;
  heat.mode = "heat2d";
  heat.grid = 32;
  heat.steps = 5;
  heat.tile = 8;
  heat.start_row = 0;
  heat.rows = 32;
  if (run_heat2d(heat) != 0) return 1;

  Args batch;
  batch.mode = "batch";
  batch.offset = 0;
  batch.count = 4;
  batch.length = 1000;
  if (run_batch(batch) != 0) return 1;

  Args irr;
  irr.mode = "irregular";
  irr.seed = 3;
  irr.work = 5000;
  if (run_irregular(irr) != 0) return 1;

  std::cerr << "selftest_ok threads=" << omp_get_max_threads() << "\n";
  return 0;
}

int main(int argc, char** argv) {
  Args a = parse_args(argc, argv);
  if (a.threads > 0) {
    omp_set_num_threads(a.threads);
  }

  if (a.mode == "heat2d") return run_heat2d(a);
  if (a.mode == "batch") return run_batch(a);
  if (a.mode == "irregular") return run_irregular(a);
  if (a.mode == "selftest") return run_selftest();

  std::cerr << "unknown mode: " << a.mode << "\n";
  return 1;
}
