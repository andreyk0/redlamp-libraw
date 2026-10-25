/* -*- C++ -*-
 * File: nikon_he_predecessor.h
 * Copyright (C) 2026 Dmitri Sotnikov
 *
   Nikon HE cross-precinct GCLI predecessor state interface

LibRaw is free software; you can redistribute it and/or modify
it under the terms of the one of two licenses as you choose:

1. GNU LESSER GENERAL PUBLIC LICENSE version 2.1
   (See file LICENSE.LGPL provided in LibRaw distribution archive for details).

2. COMMON DEVELOPMENT AND DISTRIBUTION LICENSE (CDDL) Version 1.0
   (See file LICENSE.CDDL provided in LibRaw distribution archive for details).

 */

// Nikon HE precinct predecessor state.
//
// Manages the inter-precinct GCLI prediction state for the 26 sub-bands.
// Two sub-bands use cross-band prediction (mode 0x73):
//
//   sb 12 (LL, LB 4): prev_band = sb 23 from the PREVIOUS precinct
//   sb 23 (LL, LB 7): prev_band = sb 12 from the CURRENT precinct
//
// sb 23 saves into the buffer sb 12 reads as its "previous", so it carries
// over to the next precinct; sb 12 saves into the buffer sb 23 reads, which
// is zeroed at each precinct boundary.
//
// All other sub-bands use zero-prediction (mode 0x71): prev = 0, so no
// cross-band state is needed — but GCLI values are still saved for
// consistency and potential use by the fully-insignificant flag logic.
//
// Precinct-16 reset: when precinct index == 16 and
// (Bp == 5 || (Bp == 4 && Br ≤ 7)), all GCLI prediction state is
// zeroed.
//


#ifndef LIBRAW_NIKON_HE_PREDECESSOR_H
#define LIBRAW_NIKON_HE_PREDECESSOR_H

#include "nikon_he_subband_config.h"
#include <cstdint>
#include <vector>

namespace nikon_he {

class PrecinctPredecessorState {
public:
    // Sizes the zeroed GCLI storage from the sub-band layout.
    explicit PrecinctPredecessorState(const SubbandConfig config[26]);

    // Get the "previous band" GCLI values for a sub-band.
    // For sb 12: returns sb 23's GCLIs from the previous precinct.
    // For sb 23: returns sb 12's GCLIs from the current precinct.
    // For all others: returns a zero-initialized vector (mode 0x71).
    // The returned pointer is valid until the next save_gcli() or
    // advance_precinct() call for that sub-band.
    const uint8_t* get_previous_gcli(int sb_index) const;

    // Save decoded GCLI values for a sub-band. For sb 12 and sb 23,
    // this also updates the cross-band rotation buffers.
    // gcli_values must have length ≥ config[sb_index].ng.
    void save_gcli(int sb_index, const uint8_t* gcli_values);

    // Fully-insignificant flag per sub-band.
    void set_fully_insig(int sb_index, bool flag);
    bool is_fully_insig(int sb_index) const;

    // Advance to the next precinct. Swaps rotation buffers for sb 12/23.
    void advance_precinct();

    // Get current precinct index (0-based).
    int precinct_index() const { return precinct_index_; }

    // Reset all GCLI state to zero. Called on precinct-16 boundary
    // when the reset condition is met.
    void reset_gcli_state(const SubbandConfig config[26]);

private:
    // The saved GCLIs of sub-band sb: config[sb].ng bytes, or nullptr when
    // the sub-band has no groups. Sub-bands 12 and 23 save into the rotation
    // buffers rather than into gcli_store_.
    uint8_t* gcli_store(int sb);

    // Per-sub-band GCLI storage, config[i].ng bytes each. Empty for sb 12
    // and sb 23.
    std::vector<uint8_t> gcli_store_[26];

    // Number of groups per sub-band.
    int ng_[26] = {};

    // Rotation buffers for sb 12 / sb 23 cross-band prediction, each
    // max(config[12].ng, config[23].ng) bytes.
    // rotation_buf_a_ holds previous precinct's sb 23 → current sb 12 prev.
    // rotation_buf_b_ holds current precinct's sb 12 → current sb 23 prev.
    std::vector<uint8_t> rotation_buf_a_;  // sb 23 → for sb 12 prev
    std::vector<uint8_t> rotation_buf_b_;  // sb 12 → for sb 23 prev

    // Fully-insignificant flags.
    bool fully_insig_[26] = {};

    int precinct_index_ = 0;
};

inline bool should_reset_gcli(int precinct_index, int /*Bp*/, int /*Br*/) {
    // Bp and Br are quantizer values, not precinct-position markers.
    return precinct_index == 16;
}

}  // namespace nikon_he

#endif  // LIBRAW_NIKON_HE_PREDECESSOR_H
