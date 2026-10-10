// Decodes a raw file with LibRaw, writes its photosites (raw_height rows of raw_width
// uint16 values) and prints its metadata as one JSON line.
//   dump_raw <raw file> [<photosites out>]
#include "libraw/libraw.h"

#include <chrono>
#include <cstdio>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: dump_raw <raw file> [<photosites out>]\n");
        return 64;
    }
    LibRaw p;
    const int opened = p.open_file(argv[1]);
    libraw_decoder_info_t info{};
    if (opened == LIBRAW_SUCCESS) p.get_decoder_info(&info);
    const auto start = std::chrono::steady_clock::now();
    const int unpacked = opened == LIBRAW_SUCCESS ? p.unpack() : opened;
    const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();

    const auto& S = p.imgdata.sizes;
    const auto& C = p.imgdata.color;
    char cfa[5] = {0};
    if (opened == LIBRAW_SUCCESS)
        for (int i = 0; i < 4; i++) cfa[i] = p.imgdata.idata.cdesc[p.COLOR(i / 2, i % 2)];

    std::printf("{\"file\": \"%s\", \"open\": %d, \"unpack\": %d, \"error\": \"%s\", \"decoder\": \"%s\", "
                "\"unsupported_flag\": %s, \"nef_compression\": %u, \"model\": \"%s\", "
                "\"raw_width\": %d, \"raw_height\": %d, \"width\": %d, \"height\": %d, "
                "\"top_margin\": %d, \"left_margin\": %d, \"cfa\": \"%s\", \"black\": %u, \"maximum\": %u, "
                "\"iso\": %.0f, \"shutter\": %.6f, \"aperture\": %.1f, \"cam_mul\": [%.4f, %.4f, %.4f, %.4f], "
                "\"unpack_ms\": %.1f}\n",
                argv[1], opened, unpacked, unpacked ? libraw_strerror(unpacked) : "",
                info.decoder_name ? info.decoder_name : "",
                (info.decoder_flags & LIBRAW_DECODER_UNSUPPORTED_FORMAT) ? "true" : "false",
                p.imgdata.makernotes.nikon.NEFCompression, p.imgdata.idata.model,
                S.raw_width, S.raw_height, S.width, S.height, S.top_margin, S.left_margin, cfa,
                C.black, C.maximum, p.imgdata.other.iso_speed, p.imgdata.other.shutter, p.imgdata.other.aperture,
                C.cam_mul[0], C.cam_mul[1], C.cam_mul[2], C.cam_mul[3], ms);

    if (unpacked == LIBRAW_SUCCESS && argc > 2 && p.imgdata.rawdata.raw_image) {
        FILE* out = std::fopen(argv[2], "wb");
        if (!out) return 3;
        const size_t pitch = S.raw_pitch / 2;
        for (int row = 0; row < S.raw_height; row++)
            std::fwrite(p.imgdata.rawdata.raw_image + row * pitch, 2, S.raw_width, out);
        std::fclose(out);
    }
    return unpacked == LIBRAW_SUCCESS ? 0 : 1;
}
