# The Nikon High Efficiency bench

Checks this branch's decoder for Nikon's High Efficiency NEFs (HE and HE*, `src/decoders/nikon_he/`) on the 41 CC0 samples raw.pixls.us has from the six bodies that write them: the Z 9, Z 8, Z f, Z 6III, Z5 II and Z50 II, in every mode (14 HE, 14 HE* and 13 lossless) and, where the body has them, at 3:2, 1:1 and 16:9. Each body's files are one scene shot in each mode, so every HE and HE* file has a lossless shot to be compared with. A 42nd, a Z 6III HE* file from a discuss.pixls.us Play Raw (CC BY-SA 4.0, credited in `samples.json`), comes with the DNG Adobe DNG Converter 18 made from it, so every run compares a decode with Adobe's.

```bash
redlamp/bench/bench.py quick   # after every change to the decoder: a few minutes
redlamp/bench/bench.py full    # before Redlamp pins a commit: about an hour
```

Both fetch the samples (`samples.json`, checked against their SHA-256) into `cache/`, build LibRaw as Redlamp builds it (the sources in `Makefile.dist`'s `LIB_OBJECTS`, reentrant, `-O3`), again with AddressSanitizer and UndefinedBehaviorSanitizer, and again with ThreadSanitizer, into `build/`, and write `results/<mode>-<time>/report.json`. They exit with 1 when a check fails, and list the failures.

## The checks

| Check | Passes when | quick | full |
| --- | --- | --- | --- |
| Decodes | Every HE and HE* sample decodes | All | All |
| Goldens | A sample in `goldens.json` decodes to the same mosaic (its SHA-256) | All | All |
| Colour balance | Red's and blue's gain over green are within 4% of the lossless shot's, for pairs shot at the same exposure whose block means correlate at 0.95 or more (the Z 6III's leaves move between its shots) | All | All |
| Detail (reported) | On pairs that line up exactly (no shift, correlation of at least 0.995), the share of 16 × 16-photosite blocks that differ from the lossless shot by more than 6 times the median block. Not a gate: the only such pairs are the Z50 II's, whose traffic moves between shots, so a moved car stands out as much as a decoding error | All | All |
| Adobe | Identical to Adobe DNG Converter's uncompressed mosaic, wherever `refs/` holds one: a sample's `adobe` entry is fetched there, and `full` makes the rest when the converter is installed | Where present | All |
| Sanitizers | No AddressSanitizer or UndefinedBehaviorSanitizer report | The smallest HE and HE* file per body | All 41 |
| Concurrency | One file of each size, decoded twice over on 8 threads at once, equals its serial decode | Yes | Yes |
| Data races | No ThreadSanitizer report while the same decodes run again, built with it: it finds memory two threads share unordered even when a run's timing leaves every mosaic right, such as identifications sharing `GetNormalizedModel`'s alias pointer | Yes | Yes |
| Fuzzing | No crash and no sanitizer report in runs of mutated files (headers and data of the JPEG XS stream), each run from its own generator seed; a malformed file must fail to decode, not crash | 2 seeds × 2 runs × 50 | 4 seeds × 8 runs × 500 |

`full` also draws, for each body, a crop of its smallest HE file beside its lossless shot (`sheet-<body>.png`), and the report has each decode's time.

## Goldens

`goldens.json` holds each verified sample's mosaic SHA-256. A change to the decoder must leave them unchanged unless it means to change those files' output, which takes evidence (Adobe's mosaic, or the lossless shot) in its commit. Record a sample once it's verified: `bench.py record <name>...`.

All 29 HE and HE* files have goldens. The 22 from the Z 9, Z 8, Z f, Z 6III and Z5 II were recorded from LibRaw#826 with RdWing's fixes, which RdWing reported identical to Adobe DNG Converter 17.5.1 on files from those bodies. The Z50 II's six were recorded once its band sizes and significance lengths followed JPEG XS: their colour balance is within 0.11% of their lossless shots (correlation 0.999 or more), the blocks that stand out most from those shots are traffic that moved between exposures, and against dnglab's decode of the same files (an independent decoder, used only for this check) the share of blocks where this one has detail dnglab lacks fell from 52% to 10–12%, within the 6–29% of the other bodies.

## A fuzzing crash

The report names the sample, the run's seed and the mutated file's number. `bench.py replay <name> <seed> <number> crash.nef` writes that file, which reproduces the crash under the sanitizer build (`build/san/dump_raw crash.nef`).

The Play Raw's Z 6III HE* file (`Z6_3_3x2_HEstar_4111fa11`) was recorded on 10 October 2026 after its decode matched Adobe DNG Converter 18's DNG of it in all 24,498,560 photosites.
