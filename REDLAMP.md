# Redlamp's LibRaw

This is [LibRaw](https://github.com/LibRaw/LibRaw) as [Redlamp](https://github.com/pdcgomes/redlamp) builds it: upstream LibRaw plus the changes below, each of which Redlamp needs before upstream has it. The `redlamp` branch is upstream's master at a pinned commit with these changes on top, and Redlamp pins one of its commits in `config/vendored-libs.json`. Everything here is under LibRaw's own licences (LGPL-2.1 or CDDL-1.0, at the user's choice; Redlamp uses CDDL-1.0), and every file keeps its authors and headers.

Redlamp tracks this branch as tracker row CAM-30 ([pdcgomes/redlamp#367](https://github.com/pdcgomes/redlamp/issues/367)); the HE decoder is CAM-12 ([#168](https://github.com/pdcgomes/redlamp/issues/168)).

## Base

Upstream master at `7bfffe2` (9 October 2026), the commit Redlamp pinned before this fork (CAM-13).

## Changes from upstream

| Change | Commits | Why | Upstream |
| --- | --- | --- | --- |
| Nikon High Efficiency (HE and HE*) decoder, by Dmitri Sotnikov, Yogthos and Jiang Yaogeng | The eight commits of [LibRaw#826](https://github.com/LibRaw/LibRaw/pull/826) at `499bfd4`, rebased with their authors (`8ad8c3a` to `8d2018f`) | LibRaw's `nikon_he_load_raw` is a stub that refuses these files | Not merged; LibRaw says its own decoder comes with a public snapshot |
| RdWing's four fixes to that decoder | `8fbf1ff` | The last two rows, a table overread, the exact transfer curve, raw-GCLI packets | Posted as comments on LibRaw#826 |
| Reentrancy | `0946016` | A static sub-band layout, rewritten from the width on every decode, crashed decodes of different sizes running at once | — |
| The Z50 II, and failed precincts | `5da35f3` | Significance lengths and band sizes follow JPEG XS instead of fits that broke at the Z50 II's widths; a failed precinct fails the decode instead of crashing | — |
| Malformed streams | `fedabb2` | Bounded table lookups, saturating arithmetic, checked slice headers, unverified geometries refused; the decoder no longer flagged unsupported | — |
| Camera list | `f3d2bc3` | The Z 6III, Z 8, Z 9 and Z f without the note that HE and HE* aren't supported | — |
| Model aliases, reentrant | `2a32db1` | `GetNormalizedModel` kept the alias it was matching in a static every LibRaw in a process shares, so identifications running at once could copy another camera's alias: Redlamp's decode service once named an OM-1 Mark II's model COOLPIX 900 ([pdcgomes/redlamp#444](https://github.com/pdcgomes/redlamp/issues/444)) | — |
| The bench | `redlamp/bench/` | Checks the decoder on samples of every body that writes HE files, against Adobe DNG Converter's decode, and for data races under ThreadSanitizer (`c6f39d6`) | — |

## The bench

`redlamp/bench/` checks the HE decoder against the 41 CC0 samples [raw.pixls.us](https://raw.pixls.us) has from the six bodies that write HE files, and a Z 6III HE* file whose decode matches Adobe DNG Converter's in every photosite (`redlamp/bench/README.md`). Every change to the decoder passes `redlamp/bench/bench.py quick` with the recorded goldens unchanged, and `full` before Redlamp pins it. Its parallel decodes also run under ThreadSanitizer, which reports memory that decodes on different threads share, in the decoder or in LibRaw's own identification, even when no mosaic comes out wrong.

## How Redlamp pins a commit

1. `redlamp/bench/bench.py full` passes on the commit.
2. Tag it, so that GitHub's archive of it keeps working whatever happens to the branch: `git tag pin-<first 7 of the SHA> && git push origin --tags`.
3. In Redlamp, `config/vendored-libs.json` takes the commit's full SHA as the version, `https://github.com/pdcgomes/redlamp-libraw/archive/<sha>.tar.gz` as the URL and the archive's SHA-256. Then follow "Updating LibRaw" in Redlamp's `docs/raw-pipeline.md`: `FORCE=1 scripts/vendor-libraw.sh`, the decode goldens (only the files the change meant to touch may move), the camera colour goldens, `ProcessStabilityTests` and the camera bench.

## Keeping up with upstream

Redlamp tracks LibRaw's master, merged into this branch rather than rebased onto it, so every commit Redlamp has pinned stays on the branch and nothing is force-pushed.

Every Monday the Upstream sync workflow (`.github/workflows/upstream-sync.yml`) merges LibRaw's master into a copy of this branch, runs `bench.py quick` on it and offers the result as the `upstream-sync` pull request, a draft when the bench fails; a merge that conflicts fails the run, which lists the conflicting files. Merging the pull request doesn't change what Redlamp builds. Redlamp's `scripts/release-status.py` says how many of master's commits the pinned commit lacks, so each release asks whether to adopt them.

To adopt upstream's commits:

1. Merge the `upstream-sync` pull request, or by hand: `git fetch upstream && git merge --no-ff upstream/master`. Resolve conflicts in favour of upstream outside `src/decoders/nikon_he*`, keeping each change's intent.
2. Revert any change upstream now has, and say so in the table above.
3. Update the base above, run `bench.py full`, and pin the result as above.

When LibRaw's own HE decoder lands on master or in a snapshot, the merge conflicts in `src/decoders/nikon_he*` or the bench fails; check upstream's decoder with the bench before anything else: on a branch at that upstream commit with only `redlamp/bench/` added, run `bench.py full`. If every sample decodes to its golden (or, with Adobe DNG Converter's references in `redlamp/bench/refs/`, matches Adobe's) and the sanitizer, concurrency and fuzzing checks pass, take upstream's side of the HE decoder in the merge, keep the bench, and record the switch here and in Redlamp's tracker (CAM-12, CAM-30). If it doesn't pass, keep ours and record what failed.

## Findings not yet shared upstream

These are for the owner to post, or not: on LibRaw#826, the Z50 II's crash and corruption and their causes, the static layout's race, and the fuzzing crash in `ver_lift_lb_step`, with the fixes above; on [dnglab#835](https://github.com/dnglab/dnglab/pull/835), its red 4.5% to 8.9% too strong against lossless shots of the same scenes; and to LibRaw, the race on `GetNormalizedModel`'s static alias pointer, whose one-line fix (`2a32db1`) applies to master as it is.
