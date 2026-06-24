#!/usr/bin/env python3
"""Measurement prototype: osc bse fan-out vs. bulk osc api for source resolution.

Decides the pipeline.sources strategy for the bugowner Python port.
MUST run before drafting commit 9 (pipeline/sources.py). Paste the verdict
table verbatim into commit-9's commit-message body.

Two strategies measured:
  FAN-OUT: ThreadPoolExecutor(max_workers=P) over osc bse -B <project> --csv <pkg>
  BULK:    single osc api /source/<project>?view=info&parse=1 + in-memory map

Decision rule (applied to N=real-patch binaries, threshold default 5s):
  delta >= +5s at real N  → BULK: drop Config.parallelism; use single bulk fetch
  delta <= -5s at real N  → FANOUT: lock Config.parallelism=4
  |delta| < 5s at real N but BULK wins >10s at largest synthetic N → BULK (future-proof)
  Either path >60s at any N → HALT and raise with the user

Usage:
    python scripts/prototype_osc_bse_fanout.py
    python scripts/prototype_osc_bse_fanout.py --refresh-bulk --sample test.patch
"""

import argparse
import math
import re
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from xml.etree import ElementTree as ET

OBS_HOST = "https://api.suse.de"
OBS_PROJECT = "SUSE:SLFO:Main"
BULK_CACHE = Path("/tmp/prototype_obs_bulk.xml")

# Security: refuse oversized responses before allocating an ET tree.
MAX_XML_BYTES = 50 * 1024 * 1024  # 50 MB

# osc bse --csv line format: "project|source_pkg|..."
_BSE_LINE_RE = re.compile(r"^(?P<project>[^|]+)\|(?P<source>[^|]+)")

# Same awk pattern as bot.sh: /^\+[[:space:]]+-[[:space:]]+[A-Za-z0-9]/ { print $3 }
# Strips trailing comment (#...) so "grub2-x86_64-efi # epic=foo" → "grub2-x86_64-efi"
_ADDED_PKG_RE = re.compile(r"^\+\s+-\s+([A-Za-z0-9][A-Za-z0-9_.+-]*)")


# ---------------------------------------------------------------------------
# Patch parsing

def parse_binaries_from_patch(patch_path: Path) -> list[str]:
    """Extract unique added binary names from a productcompose diff file.

    Uses the same regex as bot.sh extract_added_binaries, deduplicates, sorts.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for line in patch_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _ADDED_PKG_RE.match(line)
        if m:
            pkg = m.group(1)
            if pkg not in seen:
                seen.add(pkg)
                ordered.append(pkg)
    return sorted(ordered)


# ---------------------------------------------------------------------------
# Fan-out path

def _osc_bse_one(pkg: str, timeout: int) -> tuple[str, str | None, float, str | None]:
    """Call osc bse for one binary.

    Returns (pkg, source_or_None, elapsed_s, error_or_None).
    error values: "timeout", "exit N", "no_match"
    """
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            ["osc", "-A", OBS_HOST, "bse", "-B", OBS_PROJECT, "--csv", pkg],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return pkg, None, time.perf_counter() - t0, "timeout"
    elapsed = time.perf_counter() - t0
    if proc.returncode != 0:
        return pkg, None, elapsed, f"exit {proc.returncode}"
    for line in proc.stdout.splitlines():
        m = _BSE_LINE_RE.match(line)
        if m and m.group("project") == OBS_PROJECT:
            source = m.group("source")
            if source:
                return pkg, source, elapsed, None
    return pkg, None, elapsed, "no_match"


def run_fanout(binaries: list[str], parallelism: int, per_call_timeout: int) -> dict:
    """Run osc bse calls in parallel. Returns timing stats and failure breakdown."""
    per_call_s: list[float] = []
    n_timeout = 0
    n_nonzero = 0
    n_no_match = 0

    t_wall = time.perf_counter()
    pool = ThreadPoolExecutor(max_workers=parallelism)
    try:
        futs = {pool.submit(_osc_bse_one, pkg, per_call_timeout): pkg for pkg in binaries}
        for fut in as_completed(futs):
            _, _, elapsed, err = fut.result()
            per_call_s.append(elapsed)
            if err == "timeout":
                n_timeout += 1
            elif err is not None and err.startswith("exit"):
                n_nonzero += 1
            elif err == "no_match":
                n_no_match += 1
    except KeyboardInterrupt:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)
    wall_clock = time.perf_counter() - t_wall

    n = len(binaries)
    sorted_s = sorted(per_call_s)
    # ceil(0.95n)-1 gives the correct p95 index on a sorted list of n values.
    # int(0.95n)-1 is one slot too low for any n not divisible by 20.
    p95_idx = min(n - 1, max(0, math.ceil(0.95 * n) - 1)) if n else 0
    return {
        "n": n,
        "wall_clock": wall_clock,
        "median_ms": statistics.median(per_call_s) * 1000 if per_call_s else 0.0,
        "p95_ms": sorted_s[p95_idx] * 1000 if sorted_s else 0.0,
        "min_ms": sorted_s[0] * 1000 if sorted_s else 0.0,
        "max_ms": sorted_s[-1] * 1000 if sorted_s else 0.0,
        "throughput": n / wall_clock if wall_clock > 0 else 0.0,
        "n_timeout": n_timeout,
        "n_nonzero": n_nonzero,
        "n_no_match": n_no_match,
        "n_fail": n_timeout + n_nonzero + n_no_match,
    }


# ---------------------------------------------------------------------------
# Bulk path

def fetch_bulk_xml(project: str, cache_path: Path, refresh: bool, timeout: int) -> tuple[bytes, float]:
    """Fetch OBS bulk source-info XML. Returns (xml_bytes, fetch_elapsed_s).

    Uses cache_path as a local cache; bypass with refresh=True.
    fetch_elapsed_s is 0.0 on cache hit.
    """
    if not refresh and cache_path.exists():
        _info(
            f"[bulk] WARNING: reusing cached XML ({cache_path.stat().st_size // 1024} KiB) — "
            "fetch_s will be 0.0 and delta will exclude network cost. "
            "Run with --refresh-bulk for a decision-quality measurement."
        )
        return cache_path.read_bytes(), 0.0

    osc_path = f"/source/{project}?view=info&parse=1"
    _info(f"[bulk] fetching {osc_path} via osc api (timeout={timeout}s) ...")
    t0 = time.perf_counter()
    proc = subprocess.run(
        ["osc", "-A", OBS_HOST, "api", osc_path],
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    fetch_s = time.perf_counter() - t0
    if proc.returncode != 0:
        raise RuntimeError(
            f"osc api {osc_path!r} failed (exit {proc.returncode}):\n"
            f"{proc.stderr.decode(errors='replace')}"
        )
    xml_body = proc.stdout
    cache_path.write_bytes(xml_body)
    _info(f"[bulk] fetched {len(xml_body) // 1024} KiB in {fetch_s:.1f}s → cached at {cache_path}")
    return xml_body, fetch_s


def _build_bulk_map(xml_body: bytes) -> dict[str, str]:
    """Parse <sourceinfolist> XML into binary→canonical-source map.

    Security: size cap + DOCTYPE check before ET.fromstring.
    Logic mirrors bugownership's ObsBulkSourceInfoRepositoryImpl._build_bulk_map.
    """
    if len(xml_body) > MAX_XML_BYTES:
        raise RuntimeError(
            f"OBS bulk response exceeds {MAX_XML_BYTES // (1024 * 1024)} MB; "
            "refusing to parse"
        )
    # Real OBS responses never contain DOCTYPE; internal-entity expansion ("billion
    # laughs") can OOM the process even though ET doesn't load external entities.
    if b"<!DOCTYPE" in xml_body[:4096]:
        raise RuntimeError(
            "OBS bulk response contains a DOCTYPE declaration; refusing to parse"
        )
    try:
        root = ET.fromstring(xml_body)
    except ET.ParseError as exc:
        raise RuntimeError(f"OBS bulk response is not valid XML: {exc}") from exc

    canonical: dict[str, str] = {}
    subpacks_by_source: dict[str, list[str]] = {}

    for si in root.findall("sourceinfo"):
        pkg = si.get("package", "")
        if not pkg:
            continue
        origin = si.findtext("originpackage")
        if origin:
            canonical[pkg] = origin
        else:
            canonical.setdefault(pkg, pkg)
        subs = [text for s in si.findall("subpacks") if s.text and (text := s.text.strip())]
        if subs:
            subpacks_by_source[pkg] = subs

    def _resolve(name: str, seen: set[str] | None = None) -> str:
        seen = seen if seen is not None else set()
        if name in seen:
            return name
        seen.add(name)
        target = canonical.get(name, name)
        return target if target == name else _resolve(target, seen)

    bulk_map: dict[str, str] = {}
    for src in canonical:
        bulk_map[src] = _resolve(src)
    for src, subs in subpacks_by_source.items():
        root_src = _resolve(src)
        for sub in subs:
            existing = bulk_map.get(sub)
            if existing is None:
                bulk_map[sub] = root_src
                continue
            if existing == sub:
                continue
            if existing == root_src:
                continue
            if sub == root_src:
                bulk_map[sub] = root_src

    return bulk_map


# ---------------------------------------------------------------------------
# Verdict

def _decide(
    real_label: str,
    delta_real: float,
    delta_largest: float | None,
    threshold: float,
) -> str:
    if delta_real >= threshold:
        return "BULK"
    if delta_real <= -threshold:
        return "FANOUT"
    # TIE at real N: check if bulk wins decisively at the largest synthetic N.
    # The 10s break is fixed per the plan spec ("BULK wins decisively >10s at N=200")
    # and is intentionally not derived from `threshold` — it represents a separate
    # future-proof gate, not a scaled version of the TIE band.
    if delta_largest is not None and delta_largest > 10:
        return "BULK"
    return "FANOUT"


# ---------------------------------------------------------------------------
# Helpers

def _info(msg: str) -> None:
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# Main

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sample", type=Path, default=Path("test.patch"),
        help="Path to productcompose diff (default: ./test.patch)",
    )
    parser.add_argument(
        "--sample-size", type=int, default=None,
        help="Cap binaries from --sample (default: all unique)",
    )
    parser.add_argument(
        "--extra-N", default="50,100,200",
        help="Comma-separated synthetic sizes drawn from bulk map keys (default: 50,100,200)",
    )
    parser.add_argument(
        "--parallelism", type=int, default=4,
        help="ThreadPoolExecutor workers for fan-out (default: 4, matches Config.parallelism)",
    )
    parser.add_argument(
        "--per-call-timeout", type=int, default=30,
        help="Timeout per osc bse call in seconds (default: 30, matches Config.timeout)",
    )
    parser.add_argument(
        "--refresh-bulk", action="store_true",
        help=f"Re-fetch bulk XML even if {BULK_CACHE} exists",
    )
    parser.add_argument(
        "--threshold-seconds", type=float, default=5.0,
        help="Decision band: |delta| < threshold → TIE (default: 5.0)",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # 1. Parse binaries from patch
    if not args.sample.exists():
        _info(f"ERROR: --sample {args.sample} not found")
        return 1
    real_binaries = parse_binaries_from_patch(args.sample)
    if args.sample_size is not None:
        real_binaries = real_binaries[: args.sample_size]
    if not real_binaries:
        _info("ERROR: no binaries found in patch")
        return 1
    _info(f"[info] {len(real_binaries)} unique binaries from {args.sample}")

    # ------------------------------------------------------------------
    # 2. Fetch + parse bulk XML
    bulk_timeout = max(120, args.per_call_timeout * 4)
    xml_body, fetch_s = fetch_bulk_xml(OBS_PROJECT, BULK_CACHE, args.refresh_bulk, bulk_timeout)

    t0 = time.perf_counter()
    bulk_map = _build_bulk_map(xml_body)
    parse_ms = (time.perf_counter() - t0) * 1000
    bulk_total_s = fetch_s + parse_ms / 1000

    _info(
        f"[bulk] map: {len(bulk_map)} entries | "
        f"fetch={fetch_s:.1f}s | parse={parse_ms:.0f}ms | total={bulk_total_s:.2f}s"
    )

    if bulk_total_s > 60:
        _info(f"\nHALT: bulk total {bulk_total_s:.1f}s exceeds 60s. Raise with the user before commit 9.")
        return 2

    # ------------------------------------------------------------------
    # 3. Build sample lists for each N
    extra_ns = [int(n.strip()) for n in args.extra_N.split(",") if n.strip()]
    real_n = len(real_binaries)

    # Synthetic samples: real binaries + fill from bulk map keys not already sampled
    bulk_keys = [k for k in sorted(bulk_map.keys()) if k not in set(real_binaries)]

    measurements: list[tuple[str, list[str]]] = [(f"N={real_n}_real", real_binaries)]
    for target_n in extra_ns:
        if target_n <= real_n:
            continue
        extras_needed = target_n - real_n
        available = bulk_keys[:extras_needed]
        sample = real_binaries + available
        actual_n = len(sample)
        if actual_n < target_n:
            _info(f"[warn] only {actual_n} packages available; N={target_n} → N={actual_n}")
        measurements.append((f"N={actual_n}", sample))

    # ------------------------------------------------------------------
    # 4. Sanity baseline: fan-out at P=1 for real N
    _info(f"\n[baseline] fan-out P=1 x N={real_n} ...")
    baseline = run_fanout(real_binaries, parallelism=1, per_call_timeout=args.per_call_timeout)
    if baseline["wall_clock"] > 60:
        _info(f"\nHALT: baseline wall_clock {baseline['wall_clock']:.1f}s exceeds 60s.")
        return 2

    # ------------------------------------------------------------------
    # 5. Main measurements
    rows: list[dict] = []
    for label, binaries in measurements:
        _info(f"\n[fanout] P={args.parallelism} x {label} ...")
        result = run_fanout(binaries, parallelism=args.parallelism, per_call_timeout=args.per_call_timeout)
        if result["wall_clock"] > 60:
            _info(f"\nHALT: fanout wall_clock {result['wall_clock']:.1f}s exceeds 60s for {label}.")
            return 2
        delta = result["wall_clock"] - bulk_total_s
        rows.append({"label": label, "fanout": result, "bulk_s": bulk_total_s, "delta": delta})

    # ------------------------------------------------------------------
    # 6. Verdict
    delta_real = rows[0]["delta"]
    delta_largest = rows[-1]["delta"] if len(rows) > 1 else None
    decision = _decide(rows[0]["label"], delta_real, delta_largest, args.threshold_seconds)

    # P=1 saturation check: if speedup from P=1→P=4 is < 50% of expected, OBS is rate-limiting
    p4_wall = rows[0]["fanout"]["wall_clock"]
    p1_wall = baseline["wall_clock"]
    expected_speedup = args.parallelism
    actual_speedup = p1_wall / p4_wall if p4_wall > 0 else float("inf")
    sat_label = "SAT" if actual_speedup < expected_speedup * 0.5 else "OK"

    # ------------------------------------------------------------------
    # 7. Print verdict table (stdout — paste into commit message)
    sep = "=" * 80
    print(sep)
    print("VERDICT TABLE — paste verbatim into commit-9 commit message body")
    print(sep)
    print(
        f"project={OBS_PROJECT}  parallelism={args.parallelism}  "
        f"per_call_timeout={args.per_call_timeout}s  threshold={args.threshold_seconds}s"
    )
    print(
        f"bulk: fetch={fetch_s:.1f}s  parse={parse_ms:.0f}ms  "
        f"total={bulk_total_s:.2f}s  map_entries={len(bulk_map)}"
    )
    print()
    for row in rows:
        f = row["fanout"]
        print(
            f"{row['label']:<16}  "
            f"fanout={f['wall_clock']:.1f}s "
            f"(median={f['median_ms']:.0f}ms/call, p95={f['p95_ms']:.0f}ms, "
            f"fail={f['n_fail']})   "
            f"bulk={row['bulk_s']:.1f}s   "
            f"delta={row['delta']:+.1f}s   "
            f"[{'BULK' if row['delta'] >= args.threshold_seconds else 'FANOUT' if row['delta'] <= -args.threshold_seconds else 'TIE'}]"
        )
    print(
        f"{'P=1 baseline':<16}  "
        f"fanout={baseline['wall_clock']:.1f}s "
        f"(median={baseline['median_ms']:.0f}ms/call, P=1, "
        f"fail={baseline['n_fail']})   "
        f"speedup_vs_P{args.parallelism}={actual_speedup:.1f}x   "
        f"[{sat_label}]"
    )
    print()
    print(f"DECISION: {decision}")
    if decision == "BULK":
        print("  → adopt BULK: rewrite commit-9 as 'feat(py): pipeline.sources (single bulk fetch + in-memory map)'")
        print("  → drop Config.parallelism field and __post_init__ validation")
    else:
        print("  → keep FAN-OUT: lock Config.parallelism=4 (remove 'provisional' annotation)")
    print(sep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
