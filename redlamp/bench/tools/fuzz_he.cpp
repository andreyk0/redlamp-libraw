// Decodes a High Efficiency NEF again and again with random mutations in its JPEG XS
// stream, for running under AddressSanitizer and UndefinedBehaviorSanitizer.
//   fuzz_he <NEF> <iterations> <seed>              prints each iteration before decoding it
//   fuzz_he <NEF> <iteration> <seed> --write <out> writes that iteration's mutated file
// Mutations come from one generator seeded once, so an iteration replays exactly.
#include "libraw/libraw.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <random>
#include <string>
#include <vector>

static std::vector<uint8_t> read_file(const char* path) {
    std::vector<uint8_t> data;
    FILE* f = std::fopen(path, "rb");
    if (!f) return data;
    std::fseek(f, 0, SEEK_END);
    data.resize(std::ftell(f));
    std::fseek(f, 0, SEEK_SET);
    if (std::fread(data.data(), 1, data.size(), f) != data.size()) data.clear();
    std::fclose(f);
    return data;
}

// The JPEG XS stream starts with SOC (FF10) and CAP (FF50), whose body begins "CONTACT_INTOPIX_".
static size_t find_stream(const std::vector<uint8_t>& data) {
    static const char tag[] = "CONTACT_INTOPIX_";
    for (size_t i = 6; i + 16 < data.size(); i++)
        if (std::memcmp(&data[i], tag, 16) == 0 && data[i - 6] == 0xFF && data[i - 5] == 0x10) return i - 6;
    return 0;
}

static void mutate(std::vector<uint8_t>& buf, size_t stream, std::mt19937_64& rng) {
    const size_t end = buf.size();
    const size_t header_end = std::min(end, stream + 65536);
    std::uniform_int_distribution<int> count(1, 8), op(0, 9), byte(0, 255);
    const int n = count(rng);
    for (int k = 0; k < n; k++) {
        const bool in_headers = std::uniform_int_distribution<int>(0, 9)(rng) < 7;
        const size_t lo = stream, hi = in_headers ? header_end : end;
        const size_t at = std::uniform_int_distribution<size_t>(lo, hi - 1)(rng);
        switch (op(rng)) {
        case 0: case 1: case 2: buf[at] ^= (uint8_t)(1u << byte(rng) % 8); break;
        case 3: case 4: buf[at] = (uint8_t)byte(rng); break;
        case 5: buf[at] = 0x00; break;
        case 6: buf[at] = 0xFF; break;
        case 7: {
            const size_t from = std::uniform_int_distribution<size_t>(lo, hi - 1)(rng);
            const size_t len = std::min<size_t>({(size_t)byte(rng) + 1, end - at, end - from});
            std::memmove(&buf[at], &buf[from], len);
            break;
        }
        case 8: if (at + 2 < end) { buf[at] = 0xFF; buf[at + 1] = 0xFF; } break;
        case 9: if (std::uniform_int_distribution<int>(0, 19)(rng) == 0) buf.resize(std::max(stream + 64, at)); break;
        }
        if (buf.size() < end) break;
    }
}

int main(int argc, char** argv) {
    if (argc < 4) {
        std::fprintf(stderr, "usage: fuzz_he <NEF> <iterations> <seed> [--write <out>]\n");
        return 64;
    }
    const std::vector<uint8_t> original = read_file(argv[1]);
    const size_t stream = find_stream(original);
    if (!stream) {
        std::fprintf(stderr, "no JPEG XS stream in %s\n", argv[1]);
        return 2;
    }
    const long iterations = std::atol(argv[2]);
    std::mt19937_64 rng(std::strtoull(argv[3], nullptr, 10));
    const bool write = argc > 5 && std::strcmp(argv[4], "--write") == 0;

    std::map<std::string, long> results;
    for (long i = 1; i <= iterations; i++) {
        std::vector<uint8_t> buf = original;
        mutate(buf, stream, rng);
        if (write) {
            if (i < iterations) continue;
            FILE* out = std::fopen(argv[5], "wb");
            std::fwrite(buf.data(), 1, buf.size(), out);
            std::fclose(out);
            return 0;
        }
        std::fprintf(stderr, "iteration %ld\n", i);
        LibRaw p;
        int r = p.open_buffer(buf.data(), buf.size());
        if (r == LIBRAW_SUCCESS) r = p.unpack();
        results[r ? libraw_strerror(r) : "decoded"]++;
    }
    std::printf("{\"file\": \"%s\", \"iterations\": %ld", argv[1], iterations);
    for (const auto& [name, n] : results) std::printf(", \"%s\": %ld", name.c_str(), n);
    std::printf("}\n");
    return 0;
}
