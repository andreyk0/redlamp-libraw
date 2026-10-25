/* -*- C++ -*-
 * File: nikon_he_precinct_decode.cpp
 * Copyright (C) 2026 Dmitri Sotnikov
 *
   Nikon HE per-precinct entropy decode implementation

LibRaw is free software; you can redistribute it and/or modify
it under the terms of the one of two licenses as you choose:

1. GNU LESSER GENERAL PUBLIC LICENSE version 2.1
   (See file LICENSE.LGPL provided in LibRaw distribution archive for details).

2. COMMON DEVELOPMENT AND DISTRIBUTION LICENSE (CDDL) Version 1.0
   (See file LICENSE.CDDL provided in LibRaw distribution archive for details).

 */

// Nikon HE per-precinct entropy decode — implementation.
//
// See nikon_he_precinct_decode.h for the public API.

#include "nikon_he_precinct_decode.h"
#include "nikon_he_gcli_decode.h"
#include "nikon_he_coefficient_decode.h"
#include "nikon_he_dequantize.h"
#include "nikon_he_gtli_table.h"
#include "nikon_he_predict_lut.h"
#include <cstring>
#include <vector>

namespace nikon_he {

// Mapping from sub-band to Dpb index (16 primary + 12 secondary = 28).
// Primary (sb 0-15): Dpb[0-15]; Secondary (sb 16-25): Dpb[16-25].
static int sb_to_dpb_index(int sb) {
    if (sb < 16) return sb;
    if (sb < 26) return 16 + (sb - 16);
    return 0;
}

PrecinctDecodeResult decode_precinct(
    const uint8_t* precinct_data,
    size_t precinct_size,
    const SubbandConfig config[26],
    PrecinctPredecessorState& pred_state,
    const uint8_t* predict_lut,
    int32_t* bufA,
    int32_t* bufB) {

    PrecinctDecodeResult result = {0, false};

    // 1. Parse header
    PrecinctSizes sizes;
    if (!parse_precinct_header(precinct_data, precinct_size, config[0].layout_info->sig_bytes, sizes)) {
        return result;
    }


    // Check for precinct-16 GCLI reset
    if (should_reset_gcli(pred_state.precinct_index(), sizes.Bp, sizes.Br)) {
        pred_state.reset_gcli_state();
    }

    // 2. Walk LBs in order 0..7; within each LB, decode sub-bands in
    //    sub-band-index order (which equals priority-then-sb-order since
    //    LB 0/1/2/3/4/5/6/7's sub-band ranges are
    //    [0..5][6..11][12][13..18][19..20][21..22][23][24..25]).
    //
    //    This natural order ALSO satisfies the cross-band requirement
    //    (sb 12 decoded before sb 23 within one precinct) — LB 2 < LB 6.
    //
    //    CRITICAL: one BitReader per substream PER LB, persisted across
    //    all sub-bands of that LB. Bit state can be mid-byte at sub-band
    //    boundaries; rebuilding readers from byte cursors loses partial-
    //    byte state and desyncs the decode.
    for (int lb = 0; lb < 8; ++lb) {
        // sizes.lb_sig_offset[lb] is the byte offset within precinct_data
        // where this LB's sig substream begins (= just after its 7-byte
        // mini-header). LB mini-headers are INTERLEAVED with substreams
        // — not contiguous at the start.
        const uint8_t* sig_buf  = precinct_data + sizes.lb_sig_offset[lb];
        const uint8_t* gcli_buf = sig_buf  + sizes.lb_sig_bytes[lb];
        const uint8_t* data_buf = gcli_buf + sizes.lb_gcli_bytes[lb];
        const uint8_t* sign_buf = data_buf + sizes.lb_data_bytes[lb];

        BitReader sig_reader (sig_buf,  sizes.lb_sig_bytes[lb]);
        BitReader gcli_reader(gcli_buf, sizes.lb_gcli_bytes[lb]);
        BitReader data_reader(data_buf, sizes.lb_data_bytes[lb]);
        BitReader sign_reader(sign_buf, sizes.lb_sign_bytes[lb]);

        // Sub-band range for this LB.
        int sb_start, sb_end;
        switch (lb) {
            case 0: sb_start = 0;  sb_end = 6;  break;
            case 1: sb_start = 6;  sb_end = 12; break;
            case 2: sb_start = 12; sb_end = 13; break;
            case 3: sb_start = 13; sb_end = 19; break;
            case 4: sb_start = 19; sb_end = 21; break;
            case 5: sb_start = 21; sb_end = 23; break;
            case 6: sb_start = 23; sb_end = 24; break;
            case 7: sb_start = 24; sb_end = 26; break;
            default: continue;
        }

        for (int sb = sb_start; sb < sb_end; ++sb) {
            int ng = config[sb].ng;

            // Dpb mode from header.
            int dpb_idx = sb_to_dpb_index(sb);
            int dpb_mode = (dpb_idx >= 0 && dpb_idx < 28)
                           ? (sizes.Dpb[dpb_idx] | 0x70)
                           : 0x71;

            // GTLI for this sub-band.
            int gtli = lookup_gtli_for_sub_band(sizes.Bp, sizes.Br, sb);
            if (gtli == 0xFF) gtli = 0;

            // Predecessor GCLI (mode 0x73 cross-band; else zeros via state).
            const uint8_t* prev_gcli = pred_state.get_previous_gcli(sb);

            // 3. Decode GCLIs.
            std::vector<uint8_t> gcli_out(ng);
            if (sizes.lb_f20_sign[lb]) {
                // Raw GCLI: an absolute four-bit value per group, no prediction.
                for (int group = 0; group < ng; ++group)
                    gcli_out[group] = static_cast<uint8_t>(gcli_reader.read_bits(4));
            } else if (!decode_gcli_values(sig_reader, gcli_reader, dpb_mode,
                                           ng, gtli, predict_lut,
                                           prev_gcli, gcli_out.data())) {
                return result;
            }

            // 4. Unpack coef magnitudes.
            int coeff_count = ng * 4;
            std::vector<int32_t> coeffs(coeff_count);
            unpack_coefficient_magnitudes(data_reader, gcli_out.data(), gtli,
                                          ng, coeffs.data());

            // 5. Sign bits.
            apply_sign_bits(sign_reader, coeffs.data(), coeff_count);

            // 6. Dequantize.
            dequantize_coefficient_array(coeffs.data(), coeff_count, gcli_out.data(),
                                         ng, gtli);

            // 7. Persist GCLIs for prediction.
            pred_state.save_gcli(sb, gcli_out.data());
            bool all_zero = true;
            for (int i = 0; i < coeff_count; i++) {
                if (coeffs[i] != 0) { all_zero = false; break; }
            }
            pred_state.set_fully_insig(sb, all_zero);

            // 8. Scatter into bufA or bufB at x24*4 offset.
            int32_t* target_buf = (config[sb].buffer_idx == 0) ? bufA : bufB;
            std::memcpy(target_buf + config[sb].x24 * 4, coeffs.data(),
                        static_cast<size_t>(coeff_count) * sizeof(int32_t));

            result.total_sub_bands_decoded++;
        }

    }

    // 9. Advance precinct index
    pred_state.advance_precinct();

    result.success = (result.total_sub_bands_decoded == 26);
    return result;
}

}  // namespace nikon_he
