// Decodes several raw files at once, one LibRaw instance per thread, as Redlamp's decode
// service does, and writes each one's photosites, to compare with decodes made one at a time.
//   concurrent <threads> <raw file> <photosites out> [<raw file> <photosites out> ...]
#include "libraw/libraw.h"

#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <thread>
#include <vector>

int main(int argc, char** argv) {
    if (argc < 4 || (argc - 2) % 2) {
        std::fprintf(stderr, "usage: concurrent <threads> <raw file> <photosites out> ...\n");
        return 64;
    }
    const int threads = std::atoi(argv[1]);
    const int jobs = (argc - 2) / 2;
    std::atomic<int> next{0}, failed{0};
    std::vector<std::thread> pool;
    for (int t = 0; t < threads; t++) {
        pool.emplace_back([&] {
            for (int j; (j = next.fetch_add(1)) < jobs;) {
                // On the heap: a LibRaw is larger than a secondary thread's 512 KB stack.
                auto p = std::make_unique<LibRaw>();
                if (p->open_file(argv[2 + 2 * j]) != LIBRAW_SUCCESS || p->unpack() != LIBRAW_SUCCESS) {
                    failed++;
                    continue;
                }
                const auto& S = p->imgdata.sizes;
                FILE* out = std::fopen(argv[3 + 2 * j], "wb");
                const size_t pitch = S.raw_pitch / 2;
                for (int row = 0; row < S.raw_height; row++)
                    std::fwrite(p->imgdata.rawdata.raw_image + row * pitch, 2, S.raw_width, out);
                std::fclose(out);
            }
        });
    }
    for (auto& t : pool) t.join();
    std::printf("{\"jobs\": %d, \"failed\": %d}\n", jobs, failed.load());
    return failed ? 1 : 0;
}
