#!/usr/bin/env python3
"""Benchmark compression methods and levels on a cache directory."""
import os
import sys
import time
import tarfile
import zipfile
import shutil
import tempfile
import subprocess

DIR = sys.argv[1] if len(sys.argv) > 1 else None


def dir_size(path):
    total = 0
    for dp, _, fn in os.walk(path):
        for f in fn:
            total += os.path.getsize(os.path.join(dp, f))
    return total


def bench(name, fn):
    """Run fn() and return (name, size, seconds)."""
    t0 = time.time()
    result = fn()
    elapsed = time.time() - t0
    return (name, result, elapsed)


def run_benchmarks(base_dir):
    """Run all compression benchmarks against base_dir."""
    # Collect all subdirectories to compress (cache + cache-xml)
    subdirs = []
    for name in ("cache", "cache-xml"):
        p = os.path.join(base_dir, name)
        if os.path.isdir(p):
            subdirs.append((p, name))

    raw_size = sum(dir_size(p) for p, _ in subdirs)
    print(f"Original: {raw_size / 1024:.0f} KB")
    print(f"{'Format':<18} {'Level':>5} {'Size KB':>8} {'Ratio':>6} {'Time s':>7}")
    print("-" * 50)

    results = []

    # --- Baseline: tar (no compression) ---
    def tar_only():
        out = os.path.join(base_dir, "_bench_tar.tar")
        with tarfile.open(out, "w") as tar:
            for path, arc in subdirs:
                tar.add(path, arcname=arc)
        sz = os.path.getsize(out)
        os.unlink(out)
        return sz

    results.append(bench("tar (none)", tar_only))

    # --- tar.xz (lzma) ---
    for level in (1, 5, 9):
        lvl = level
        def xz_compress(lvl=lvl):
            out = os.path.join(base_dir, "_bench.tar.xz")
            with tarfile.open(out, "w:xz", preset=lvl) as tar:
                for path, arc in subdirs:
                    tar.add(path, arcname=arc)
            sz = os.path.getsize(out)
            os.unlink(out)
            return sz
        results.append(bench(f"tar.xz  ", xz_compress))

    # --- tar.gz (gzip) ---
    for level in (1, 5, 9):
        lvl = level
        def gz_compress(lvl=lvl):
            out = os.path.join(base_dir, "_bench.tar.gz")
            with tarfile.open(out, "w:gz", compresslevel=lvl) as tar:
                for path, arc in subdirs:
                    tar.add(path, arcname=arc)
            sz = os.path.getsize(out)
            os.unlink(out)
            return sz
        results.append(bench(f"tar.gz  ", gz_compress))

    # --- zip (deflate) ---
    for level in (1, 5, 9):
        lvl = level
        def zip_compress(lvl=lvl):
            out = os.path.join(base_dir, "_bench.zip")
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=lvl) as zf:
                for path, arc in subdirs:
                    for dp, _, fn in os.walk(path):
                        for f in fn:
                            fp = os.path.join(dp, f)
                            ap = os.path.join(arc, os.path.relpath(fp, path))
                            zf.write(fp, ap)
            sz = os.path.getsize(out)
            os.unlink(out)
            return sz
        results.append(bench(f"zip     ", zip_compress))

    # --- 7z (if available) ---
    seven_z = shutil.which("7z") or shutil.which("7zz") or shutil.which("7za")
    if seven_z:
        for level in (1, 5, 9):
            lvl = level
            def seven_compress(lvl=lvl):
                out = os.path.join(base_dir, "_bench.7z")
                # Build a temp dir with the subdirs
                tmp = os.path.join(base_dir, "_bench_tmp")
                os.makedirs(tmp, exist_ok=True)
                for path, arc in subdirs:
                    dst = os.path.join(tmp, arc)
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(path, dst)
                subprocess.run(
                    [seven_z, "a", "-mx=" + str(lvl), "-bso0", "-bse0", out, tmp + "/*"],
                    check=True, timeout=120,
                )
                sz = os.path.getsize(out)
                shutil.rmtree(tmp)
                os.unlink(out)
                return sz
            results.append(bench(f"7z      ", seven_compress))

    # Print results sorted by size
    results.sort(key=lambda r: r[1])
    for name, sz, elapsed in results:
        ratio = (1 - sz / raw_size) * 100 if raw_size else 0
        level = name.split()[-1] if name.split()[-1].isdigit() else "-"
        fmt = name.rsplit(None, 1)[0] if name.split()[-1].isdigit() else name
        print(f"{fmt:<18} {level:>5} {sz/1024:>8.0f} {ratio:>5.0f}% {elapsed:>6.1f}s")


if __name__ == "__main__":
    base = DIR or os.path.join(
        "sites", "www.whitehouse.gov",
        sorted(os.listdir("sites/www.whitehouse.gov"))[-1]
    )
    print(f"Benchmarking: {base}")
    run_benchmarks(base)
