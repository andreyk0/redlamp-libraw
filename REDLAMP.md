# Redlamp's LibRaw

This is [LibRaw](https://github.com/LibRaw/LibRaw) as [Redlamp](https://github.com/pdcgomes/redlamp) builds it: upstream LibRaw plus the changes below, each of which Redlamp needs before upstream has it. The `redlamp` branch is upstream's master at a pinned commit with these changes on top, and Redlamp pins one of its commits in `config/vendored-libs.json`. Everything here is under LibRaw's own licences (LGPL-2.1 or CDDL-1.0, at the user's choice; Redlamp uses CDDL-1.0), and every file keeps its authors and headers.

Redlamp tracks this branch as tracker row CAM-30 ([pdcgomes/redlamp#367](https://github.com/pdcgomes/redlamp/issues/367)).

## Base

Upstream master at `7bfffe2` (9 October 2026), the commit Redlamp pinned before this fork (CAM-13).

## Changes from upstream

| Change | Commits | Why | Tracker | Upstream |
| --- | --- | --- | --- | --- |
| Nikon High Efficiency (HE and HE*) decoder, by Dmitri Sotnikov and Jiang Yaogeng | The eight commits of [LibRaw#826](https://github.com/LibRaw/LibRaw/pull/826) at `499bfd4`, rebased with their authors | LibRaw's `nikon_he_load_raw` is a stub that refuses these files | CAM-12 | Not merged; LibRaw says its own decoder comes with a public snapshot |
| RdWing's four fixes to that decoder | `8fbf1ff` | The last two rows, a table overread, the exact transfer curve, raw-GCLI packets | CAM-12 | Posted as comments on LibRaw#826 |

## The bench

`redlamp/bench/` checks the HE decoder against CC0 samples from [raw.pixls.us](https://raw.pixls.us). Every change to the decoder passes `redlamp/bench/bench.py quick` with the recorded goldens unchanged, and `full` before Redlamp pins it. See `redlamp/bench/README.md`.
