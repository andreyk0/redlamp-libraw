#!/usr/bin/env python3
"""The Nikon High Efficiency bench: checks this branch's HE decoder on CC0 samples.

    bench.py fetch                 download the samples in samples.json into cache/
    bench.py build                 build LibRaw and the tools, optimised and with sanitizers
    bench.py quick [--only TEXT]   the checks to run after every change
    bench.py full  [--only TEXT]   every check, before Redlamp pins a commit
    bench.py record NAME...        record goldens (the mosaic's SHA-256) for these samples
    bench.py replay NAME SEED N OUT  write fuzzing run SEED's Nth mutated file of NAME

Checks: every HE and HE* sample decodes; mosaics match their goldens; colour balance and
detail against the same body's lossless shot; Adobe DNG Converter's output, photosite by
photosite, where refs/ has it (full makes it when the converter is installed); the
sanitizers; parallel decodes against serial ones, and under ThreadSanitizer; seeded fuzzing; speed; and a sheet of
crops beside the lossless shots (full). Results go to results/<time>/report.json.
LibRaw is built as Redlamp builds it: Makefile.dist's LIB_OBJECTS, reentrant.
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.request

import numpy as np

BENCH = pathlib.Path(__file__).resolve().parent
ROOT = BENCH.parents[1]
CACHE, BUILD, RESULTS, REFS = BENCH / "cache", BENCH / "build", BENCH / "results", BENCH / "refs"
FLAGS = {
    "opt": "-std=c++17 -O3 -w -DUSE_ZLIB -DLIBRAW_NODLL",
    "san": "-std=c++17 -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -w -DUSE_ZLIB -DLIBRAW_NODLL",
    "tsan": "-std=c++17 -O1 -g -fno-omit-frame-pointer -fsanitize=thread -w -DUSE_ZLIB -DLIBRAW_NODLL",
}
TOOLS = ("dump_raw", "fuzz_he", "concurrent")
ADOBE = pathlib.Path("/Applications/Adobe DNG Converter.app/Contents/MacOS/Adobe DNG Converter")
SAN_ENV = {"ASAN_OPTIONS": "halt_on_error=1:detect_leaks=0", "UBSAN_OPTIONS": "print_stacktrace=1:report_error_type=1"}
TSAN_ENV = {"TSAN_OPTIONS": "halt_on_error=0"}
# Gates. Colour balance: red's and blue's gain over green against the lossless shot, for pairs
# shot at the same exposure whose block means correlate at least SIMILAR (the Z 6III's leaves
# move between shots). Detail: on pairs that line up exactly (no shift, correlation of at
# least ALIGNED), the share of 16 x 16 blocks whose difference from the lossless shot is
# OUTLIER times the median block's.
BALANCE, SIMILAR, ALIGNED, OUTLIER, OUTLIER_SHARE = 0.04, 0.95, 0.995, 6.0, 0.002
FUZZ = {"quick": (2, 2, 50), "full": (4, 8, 500)}  # seeds, runs per seed, mutated files per run
FUZZ_SEEDS = ("Z5_2_3x2_HE_196971ea", "Zf_3x2_HE_98d6ca8e", "Z6_3_3x2_HE_a8fa2cac", "Z5_2_3x2_HEstar_276ef4ad")


def samples():
    return json.loads((BENCH / "samples.json").read_text())["samples"]


def goldens():
    path = BENCH / "goldens.json"
    return json.loads(path.read_text()) if path.exists() else {}


def nef(s):
    return CACHE / f"{s['name']}.NEF"


# ---------------------------------------------------------------- fetch and build

def fetch():
    CACHE.mkdir(exist_ok=True)
    REFS.mkdir(exist_ok=True)
    for s in samples():
        files = [(nef(s), s["url"], s["sha256"])]
        if "adobe" in s:
            files.append((REFS / f"{s['name']}.dng", s["adobe"]["url"], s["adobe"]["sha256"]))
        for path, url, sha256 in files:
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha256:
                continue
            data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "redlamp-bench"}),
                                          timeout=300).read()
            if hashlib.sha256(data).hexdigest() != sha256:
                sys.exit(f"{path.name}: checksum mismatch")
            path.write_bytes(data)
            print("fetched", path.name, flush=True)
            time.sleep(1)  # raw.pixls.us and discuss.pixls.us are run by volunteers


def lib_sources():
    text = (ROOT / "Makefile.dist").read_text()
    block = re.search(r"^LIB_OBJECTS=(.*?)(?<!\\)\n", text, re.S | re.M).group(1)
    sources = []
    for obj in re.findall(r"object/(\S+)\.o", block):
        match = sorted(ROOT.joinpath("src").rglob(f"{obj}.cpp"))
        if not match:
            sys.exit(f"no source for {obj}")
        sources.append(match[0])
    return sources


def stale(obj, dep):
    if not obj.exists() or not dep.exists():
        return True
    built = obj.stat().st_mtime
    files = dep.read_text().replace("\\\n", " ").split(":", 1)[1].split()
    return any(not pathlib.Path(f).exists() or pathlib.Path(f).stat().st_mtime > built for f in files)


def build(variants=("opt", "san", "tsan")):
    jobs = os.cpu_count() // 2 or 1
    for variant in variants:
        out = BUILD / variant
        objs = out / "obj"
        objs.mkdir(parents=True, exist_ok=True)
        flags = FLAGS[variant].split() + [f"-I{ROOT}"]

        def compile_one(src):
            obj, dep = objs / f"{src.stem}.o", objs / f"{src.stem}.d"
            if not stale(obj, dep):
                return None
            r = subprocess.run(["clang++", "-c", str(src), "-o", str(obj), "-MMD", "-MF", str(dep), *flags],
                               capture_output=True, text=True)
            return None if r.returncode == 0 else f"{src.name}: {r.stderr[-2000:]}"

        with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
            errors = [e for e in pool.map(compile_one, lib_sources()) if e]
        if errors:
            sys.exit("\n".join(errors))
        lib = out / "libraw.a"
        subprocess.run(["libtool", "-static", "-o", str(lib), *map(str, sorted(objs.glob("*.o")))],
                       check=True, capture_output=True)
        for tool in TOOLS:
            subprocess.run(["clang++", *flags, str(BENCH / "tools" / f"{tool}.cpp"), str(lib), "-lz",
                            "-o", str(out / tool)], check=True)
        print(f"built {variant}", flush=True)


# ---------------------------------------------------------------- decoding

def decode(variant, path, mosaic=None, env=None):
    cmd = [str(BUILD / variant / "dump_raw"), str(path)] + ([str(mosaic)] if mosaic else [])
    r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    lines = [l for l in r.stdout.splitlines() if l.startswith("{")]
    meta = json.loads(lines[-1]) if lines else {"unpack": None, "error": f"exit {r.returncode}"}
    meta["exit"], meta["stderr"] = r.returncode, r.stderr
    return meta


def load(meta, path):
    return np.fromfile(path, dtype="<u2").reshape(meta["raw_height"], meta["raw_width"])


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------- comparisons

def blocks(img, black, y, x, b=8):
    c = img[y::2, x::2].astype(np.float64) - black
    h, w = c.shape[0] // b * b, c.shape[1] // b * b
    return c[:h, :w].reshape(h // b, b, w // b, b).mean(axis=(1, 3))


def shift_between(a, b):
    fa, fb = np.fft.fft2(a - a.mean()), np.fft.fft2(b - b.mean())
    r = fa * np.conj(fb)
    peak = np.unravel_index(np.argmax(np.abs(np.fft.ifft2(r / (np.abs(r) + 1e-9)))), a.shape)
    return [int(p if p <= s // 2 else p - s) for p, s in zip(peak, a.shape)]


def overlap(a, b, dy, dx):
    h, w = a.shape[:2]
    return (a[max(0, dy):h + min(0, dy), max(0, dx):w + min(0, dx)],
            b[max(0, -dy):h + min(0, -dy), max(0, -dx):w + min(0, -dx)])


def against_lossless(he, he_black, ll, ll_black):
    """Colour balance by aligned block means, and, when the pair lines up exactly, the share of
    16 x 16-photosite blocks whose difference stands out from the rest."""
    dy, dx = shift_between(blocks(he, he_black, 0, 1), blocks(ll, ll_black, 0, 1))
    slopes, r_g = {}, None
    for name, (y, x) in {"R": (0, 0), "G1": (0, 1), "G2": (1, 0), "B": (1, 1)}.items():
        a, l = overlap(blocks(he, he_black, y, x), blocks(ll, ll_black, y, x), dy, dx)
        a, l = a.ravel(), l.ravel()
        slopes[name] = float((a * l).sum() / (l * l).sum())
        if name == "G1":
            r_g = float(np.corrcoef(a, l)[0, 1])
    g = (slopes["G1"] + slopes["G2"]) / 2
    out = {"shift_blocks": [dy, dx], "r": r_g, "R_over_G": slopes["R"] / g, "B_over_G": slopes["B"] / g}
    if [dy, dx] == [0, 0] and r_g >= ALIGNED:
        rms = []
        for y, x in ((0, 0), (0, 1), (1, 0), (1, 1)):
            a = he[y::2, x::2].astype(np.float64) - he_black
            l = ll[y::2, x::2].astype(np.float64) - ll_black
            k = (a * l).sum() / (l * l).sum()
            d = a - k * l
            h, w = d.shape[0] // 8 * 8, d.shape[1] // 8 * 8
            rms.append(np.sqrt((d[:h, :w] ** 2).reshape(h // 8, 8, w // 8, 8).mean(axis=(1, 3))))
        rms = np.maximum.reduce(rms)
        out["outlier_share"] = float((rms > OUTLIER * np.median(rms)).mean())
    return out


def against_adobe(he, ref):
    """Adobe's DNG may be cropped; find the offset where the two match, then compare everywhere."""
    h, w = ref.shape
    cy, cx = h // 2, w // 2
    window = ref[cy - 64:cy + 64, cx - 64:cx + 64]
    best = None
    for dy in range(-32, 33):
        for dx in range(-32, 33):
            y, x = cy - 64 + dy + (he.shape[0] - h) // 2, cx - 64 + dx + (he.shape[1] - w) // 2
            if y < 0 or x < 0 or y + 128 > he.shape[0] or x + 128 > he.shape[1]:
                continue
            same = int((he[y:y + 128, x:x + 128] == window).sum())
            if best is None or same > best[0]:
                best = (same, y - (cy - 64), x - (cx - 64))
    _, oy, ox = best
    a = he[max(0, oy):max(0, oy) + h, max(0, ox):max(0, ox) + w].astype(np.int32)
    b = ref[:a.shape[0], :a.shape[1]].astype(np.int32)
    d = np.abs(a - b)
    return {"offset": [int(oy), int(ox)], "identical": float((d == 0).mean()), "max": int(d.max())}


# ---------------------------------------------------------------- the run

def run(mode, only):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RESULTS / f"{mode}-{stamp}"
    mos = BUILD / "mosaics"
    out.mkdir(parents=True)
    mos.mkdir(parents=True, exist_ok=True)
    all_samples = samples()
    chosen = [s for s in all_samples if not only or only in s["name"]]
    he = [s for s in chosen if s["mode"] != "lossless"]
    gold = goldens()
    report = {"mode": mode, "commit": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                                     capture_output=True, text=True).stdout.strip(),
              "samples": {}, "failures": []}
    fail = report["failures"].append

    # Decodes, goldens and speed.
    decoded = {}
    for s in chosen:
        meta = decode("opt", nef(s), mos / f"{s['name']}.u16")
        rec = {k: meta.get(k) for k in ("unpack", "error", "exit", "decoder", "unsupported_flag", "raw_width",
                                        "raw_height", "black", "maximum", "unpack_ms")}
        if meta.get("unpack") == 0:
            decoded[s["name"]] = meta
            rec["sha256"] = sha(mos / f"{s['name']}.u16")
            g = gold.get(s["name"])
            if g:
                rec["golden"] = rec["sha256"] == g["sha256"]
                if not rec["golden"]:
                    fail(f"{s['name']}: mosaic differs from its golden")
        elif s["mode"] != "lossless":
            fail(f"{s['name']}: doesn't decode ({meta.get('error')}, exit {meta.get('exit')})")
        report["samples"][s["name"]] = rec
        print(f"{s['name']:32} {'decoded' if meta.get('unpack') == 0 else meta.get('error') or meta.get('exit')}"
              f"{'' if 'golden' not in rec else ('  golden ok' if rec['golden'] else '  GOLDEN DIFFERS')}", flush=True)

    # Against the lossless shot of the same scene, decoded by this same build.
    lossless = {(s["model"], decoded[s["name"]]["raw_width"], decoded[s["name"]]["raw_height"]): s
                for s in all_samples if s["mode"] == "lossless" and s["name"] in decoded}
    for s in all_samples:
        if s["mode"] == "lossless" and s["name"] not in decoded and any(c["model"] == s["model"] for c in he):
            meta = decode("opt", nef(s), mos / f"{s['name']}.u16")
            if meta.get("unpack") == 0:
                decoded[s["name"]] = meta
                lossless[(s["model"], meta["raw_width"], meta["raw_height"])] = s
    for s in he:
        meta = decoded.get(s["name"])
        pair = meta and lossless.get((s["model"], meta["raw_width"], meta["raw_height"]))
        if not pair:
            continue
        lm = decoded[pair["name"]]
        cmp = against_lossless(load(meta, mos / f"{s['name']}.u16"), meta["black"],
                               load(lm, mos / f"{pair['name']}.u16"), lm["black"])
        cmp["lossless"] = pair["name"]
        cmp["same_exposure"] = all(meta[k] == lm[k] for k in ("iso", "shutter", "aperture"))
        report["samples"][s["name"]]["lossless"] = cmp
        if cmp["same_exposure"] and cmp["r"] >= SIMILAR and max(abs(cmp["R_over_G"] - 1),
                                                                 abs(cmp["B_over_G"] - 1)) > BALANCE:
            fail(f"{s['name']}: colour balance against its lossless shot R/G {cmp['R_over_G']:.3f} B/G {cmp['B_over_G']:.3f}")
        # Reported, not a gate: the only pairs that line up exactly are the Z50 II's, whose
        # town view has traffic moving between shots, so moved cars stand out as much as a
        # decoding error does. Its six files are held by their goldens instead.
        if cmp.get("outlier_share", 0) > OUTLIER_SHARE:
            report.setdefault("notes", []).append(
                f"{s['name']}: {cmp['outlier_share']:.2%} of blocks stand out from its aligned lossless shot")

    # Adobe DNG Converter's mosaics.
    if mode == "full" and ADOBE.exists():
        REFS.mkdir(exist_ok=True)
        for s in he:
            if not (REFS / f"{s['name']}.dng").exists():
                subprocess.run([str(ADOBE), "-u", "-p0", "-d", str(REFS), str(nef(s))], capture_output=True)
    for s in he:
        ref = REFS / f"{s['name']}.dng"
        if ref.exists() and s["name"] in decoded:
            rm = decode("opt", ref, mos / "adobe.u16")
            if rm.get("unpack") != 0:
                fail(f"{s['name']}: Adobe's DNG doesn't decode")
                continue
            cmp = against_adobe(load(decoded[s["name"]], mos / f"{s['name']}.u16"), load(rm, mos / "adobe.u16"))
            report["samples"][s["name"]]["adobe"] = cmp
            if cmp["identical"] < 1:
                fail(f"{s['name']}: {1 - cmp['identical']:.4%} of photosites differ from Adobe's (max {cmp['max']})")

    # Sanitizers.
    san_set = chosen if mode == "full" else [s for s in he if s["name"] == min(
        (c["name"] for c in he if c["model"] == s["model"] and c["mode"] == s["mode"]),
        key=lambda n: next(c["megabytes"] for c in he if c["name"] == n))]
    with concurrent.futures.ThreadPoolExecutor(max(1, os.cpu_count() // 4)) as pool:
        results = list(pool.map(lambda s: (s, decode("san", nef(s), env=SAN_ENV)), san_set))
    for s, meta in results:
        reports = re.findall(r"ERROR: AddressSanitizer: [\w-]+|runtime error: [^\n]{0,80}", meta["stderr"])
        report["samples"][s["name"]]["sanitizers"] = sorted(set(reports))
        if reports:
            (out / f"sanitizers-{s['name']}.txt").write_text(meta["stderr"])
            fail(f"{s['name']}: sanitizers: {reports[0]}")
    print(f"sanitizers: {len(san_set)} files", flush=True)

    # Parallel decodes against serial ones: one file of each size, twice over.
    sizes = {}
    for s in he:
        m = decoded.get(s["name"])
        if m:
            sizes.setdefault((m["raw_width"], m["raw_height"]), s)
    jobs = [(s, i) for i in range(2) for s in sizes.values()]
    if len(jobs) > 1:
        args = [str(BUILD / "opt" / "concurrent"), "8"]
        for s, i in jobs:
            args += [str(nef(s)), str(mos / f"par-{i}-{s['name']}.u16")]
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode:
            fail(f"concurrency: the parallel decodes stopped (exit {r.returncode})")
        for s, i in jobs:
            p = mos / f"par-{i}-{s['name']}.u16"
            if not p.exists() or sha(p) != report["samples"][s["name"]]["sha256"]:
                fail(f"{s['name']}: a parallel decode differs from the serial one")
        print(f"concurrency: {len(jobs)} decodes on 8 threads", flush=True)

        # Again with ThreadSanitizer, which reports memory two threads share unordered even when
        # this run's timing left every mosaic right.
        args = [str(BUILD / "tsan" / "concurrent"), "8"]
        for s, _ in jobs:
            args += [str(nef(s)), os.devnull]
        r = subprocess.run(args, capture_output=True, text=True, env={**os.environ, **TSAN_ENV})
        races = re.findall(r"WARNING: ThreadSanitizer: ([^(\n]+?) \(pid", r.stderr)
        report["data_races"] = len(races)
        if races:
            (out / "tsan.txt").write_text(r.stderr)
            first = r.stderr.split("WARNING: ThreadSanitizer:")[1]
            where = re.search(r"Location is (.+?)(?: at 0x\S+.*)?$", first, re.M) or re.search(r"#0 (\S+)", first)
            fail(f"data races: {len(races)} ThreadSanitizer reports, the first a {races[0]} "
                 f"in {where.group(1) if where else 'an unknown place'}")
        elif r.returncode:
            fail(f"data races: the decodes under ThreadSanitizer stopped (exit {r.returncode})")
        print(f"data races: {len(races)} in {len(jobs)} decodes on 8 threads", flush=True)

    # Fuzzing.
    seeds, runs, iterations = FUZZ[mode]
    crashes = []
    tasks = [(name, seed) for name in FUZZ_SEEDS[:seeds] for seed in range(1, runs + 1)
             if not only or only in name]

    def fuzz(task):
        name, seed = task
        r = subprocess.run([str(BUILD / "san" / "fuzz_he"), str(CACHE / f"{name}.NEF"), str(iterations), str(seed)],
                           capture_output=True, text=True, env={**os.environ, **SAN_ENV})
        ub = re.search(r"(src/\S+): runtime error: ([^\n]{0,80})", r.stderr)
        if r.returncode == 0 and not ub:
            return None
        # An undefined-behaviour report doesn't stop the run; the iteration before it names the file.
        last = re.findall(r"iteration (\d+)", r.stderr[:ub.start()] if ub and r.returncode == 0 else r.stderr)
        kind = re.search(r"ERROR: AddressSanitizer: ([\w-]+)", r.stderr)
        frame = re.search(r"#0 0x[0-9a-f]+ in (\S+)", r.stderr)
        crash = {"sample": name, "seed": seed, "iteration": int(last[-1]) if last else None,
                 "error": kind.group(1) if kind else (f"undefined behaviour: {ub.group(2)}" if ub else f"exit {r.returncode}"),
                 "frame": frame.group(1) if frame else (ub.group(1) if ub else None)}
        (out / f"fuzz-{name}-{seed}.txt").write_text(r.stderr[-20000:])
        return crash

    with concurrent.futures.ThreadPoolExecutor(max(1, os.cpu_count() // 4)) as pool:
        crashes = [c for c in pool.map(fuzz, tasks) if c]
    report["fuzz"] = {"runs": len(tasks), "mutated_files_per_run": iterations, "crashes": crashes}
    for c in crashes:
        fail(f"fuzz: {c['sample']} seed {c['seed']} iteration {c['iteration']}: {c['error']} in {c['frame']}")
    print(f"fuzzing: {len(tasks)} runs of up to {iterations}, {len(crashes)} crashed", flush=True)

    if mode == "full":
        sheets(he, decoded, lossless, mos, out)

    (out / "report.json").write_text(json.dumps(report, indent=1))
    print(f"\n{len(report['failures'])} failures; report in {out.relative_to(BENCH)}")
    for f in report["failures"]:
        print("  " + f)
    return 1 if report["failures"] else 0


def sheets(he, decoded, lossless, mos, out):
    """For each body, its smallest HE file beside its lossless shot, 2 x 2 quads as pixels."""
    done = set()
    for s in sorted(he, key=lambda s: s["megabytes"]):
        meta = decoded.get(s["name"])
        pair = meta and lossless.get((s["model"], meta["raw_width"], meta["raw_height"]))
        if not pair or s["model"] in done:
            continue
        done.add(s["model"])
        lm = decoded[pair["name"]]
        a, l = load(meta, mos / f"{s['name']}.u16"), load(lm, mos / f"{pair['name']}.u16")
        q = lambda m, b: np.stack([m[0::2, 0::2] - b, (m[0::2, 1::2] / 2 + m[1::2, 0::2] / 2) - b, m[1::2, 1::2] - b], -1)
        A, L = q(a.astype(np.float64), meta["black"]), q(l.astype(np.float64), lm["black"])
        h, w = 240, 360
        y, x = (L.shape[0] - h) // 2, (L.shape[1] - w) // 2
        wb = np.array([lm["cam_mul"][0], 1, lm["cam_mul"][2]])
        scale = np.percentile(L[y:y + h, x:x + w] * wb, 99.5)
        img = np.concatenate([L[y:y + h, x:x + w], np.full((h, 8, 3), 0.0), A[y:y + h, x:x + w]], axis=1)
        img = (np.clip(img * wb / scale, 0, 1) ** (1 / 2.2) * 255 + 0.5).astype(np.uint8)
        ppm = out / f"sheet-{s['model'].replace(' ', '')}.ppm"
        ppm.write_bytes(f"P6 {img.shape[1]} {img.shape[0]} 255\n".encode() + img.tobytes())
        subprocess.run(["sips", "-s", "format", "png", str(ppm), "--out", str(ppm.with_suffix(".png"))],
                       capture_output=True)
        ppm.unlink()


def record(names):
    gold = goldens()
    by_name = {s["name"]: s for s in samples()}
    mos = BUILD / "mosaics"
    mos.mkdir(parents=True, exist_ok=True)
    for name in names:
        meta = decode("opt", nef(by_name[name]), mos / "record.u16")
        if meta.get("unpack") != 0:
            sys.exit(f"{name}: doesn't decode")
        gold[name] = {"sha256": sha(mos / "record.u16"), "raw_width": meta["raw_width"],
                      "raw_height": meta["raw_height"], "black": meta["black"], "maximum": meta["maximum"]}
        print("recorded", name)
    (BENCH / "goldens.json").write_text(json.dumps(dict(sorted(gold.items())), indent=1) + "\n")


def replay(name, seed, iteration, out):
    subprocess.run([str(BUILD / "san" / "fuzz_he"), str(CACHE / f"{name}.NEF"), str(iteration), str(seed),
                    "--write", out], check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    sub.add_parser("build")
    for m in ("quick", "full"):
        sub.add_parser(m).add_argument("--only")
    sub.add_parser("record").add_argument("names", nargs="+")
    r = sub.add_parser("replay")
    for a in ("name", "seed", "iteration", "out"):
        r.add_argument(a)
    a = p.parse_args()
    if a.cmd == "fetch":
        fetch()
    elif a.cmd == "build":
        build()
    elif a.cmd in ("quick", "full"):
        fetch()
        build()
        sys.exit(run(a.cmd, a.only))
    elif a.cmd == "record":
        build(("opt",))
        record(a.names)
    else:
        replay(a.name, a.seed, a.iteration, a.out)


if __name__ == "__main__":
    main()
