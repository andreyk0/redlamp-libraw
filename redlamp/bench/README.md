# The Nikon High Efficiency bench

Checks this branch's decoder for Nikon's High Efficiency NEFs (HE and HE*, `src/decoders/nikon_he/`) on the 41 CC0 samples raw.pixls.us has from the six bodies that write them: the Z 9, Z 8, Z f, Z 6III, Z5 II and Z50 II, in every mode (14 HE, 14 HE* and 13 lossless) and, where the body has them, at 3:2, 1:1 and 16:9. Each body's files are one scene shot in each mode, so every HE and HE* file has a lossless shot to be compared with.

```bash
redlamp/bench/bench.py quick   # after every change to the decoder: a few minutes
redlamp/bench/bench.py full    # before Redlamp pins a commit: about an hour
```

Both fetch the samples (`samples.json`, checked against their SHA-256) into `cache/`, build LibRaw as Redlamp builds it (the sources in `Makefile.dist`'s `LIB_OBJECTS`, reentrant, `-O3`) and again with AddressSanitizer and UndefinedBehaviorSanitizer into `build/`, and write `results/<mode>-<time>/report.json`. They exit with 1 when a check fails, and list the failures.

## The checks

| Check | Passes when | quick | full |
| --- | --- | --- | --- |
| Decodes | Every HE and HE* sample decodes | All | All |
| Goldens | A sample in `goldens.json` decodes to the same mosaic (its SHA-256) | All | All |
| Colour balance | Red's and blue's gain over green are within 4% of the lossless shot's, for pairs shot at the same exposure whose block means correlate at 0.95 or more (the Z 6III's leaves move between its shots) | All | All |
| Detail | On pairs that line up exactly (no shift, correlation of at least 0.995), at most 0.2% of 16 × 16-photosite blocks differ from the lossless shot by more than 6 times the median block | All | All |
| Adobe | Identical to Adobe DNG Converter's uncompressed mosaic, wherever `refs/` holds one; `full` makes them when the converter is installed | Where present | All |
| Sanitizers | No AddressSanitizer or UndefinedBehaviorSanitizer report | The smallest HE and HE* file per body | All 41 |
| Concurrency | One file of each size, decoded twice over on 8 threads at once, equals its serial decode | Yes | Yes |
| Fuzzing | No crash in runs of mutated files (headers and data of the JPEG XS stream), each run from its own generator seed | 2 seeds × 2 runs × 50 | 4 seeds × 8 runs × 500 |

`full` also draws, for each body, a crop of its smallest HE file beside its lossless shot (`sheet-<body>.png`), and the report has each decode's time.

## Goldens

`goldens.json` holds each verified sample's mosaic SHA-256. A change to the decoder must leave them unchanged unless it means to change those files' output, which takes evidence (Adobe's mosaic, or the lossless shot) in its commit. Record a sample once it's verified: `bench.py record <name>...`.

## A fuzzing crash

The report names the sample, the run's seed and the mutated file's number. `bench.py replay <name> <seed> <number> crash.nef` writes that file, which reproduces the crash under the sanitizer build (`build/san/dump_raw crash.nef`).
