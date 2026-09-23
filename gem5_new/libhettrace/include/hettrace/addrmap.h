// Address and source identities for the Vortex CP DMA memory trace.
#ifndef HETTRACE_ADDRMAP_H_
#define HETTRACE_ADDRMAP_H_

#include <cstddef>
#include <cstdint>

namespace hettrace {
constexpr int kMapAddrBits = 64;
constexpr uint64_t kTicksPerSecond = 1000000000000ull;
enum SrcId : uint16_t { kSrcHost = 0, kSrcVortex = 1, kSrcCount = 2 };
enum TapLevel : uint8_t {
    kLevelPostLlc = 0, kLevelPreCache = 1,
    kLevelAxiMaster = 2, kLevelInterconnect = 3
};
constexpr uint64_t kClockPeriodTicks_host = 500ull;
constexpr uint64_t kClockPeriodTicks_vortex = 1000ull;
constexpr uint64_t kVortexCpBase = 0x20000000ull;
constexpr uint64_t kVortexCpSize = 0x200ull;
constexpr uint64_t kHostHeapBase = 0x80000000ull;
constexpr uint64_t kHostHeapSize = 0x10000000ull;
constexpr uint64_t kVortexBarBase = 0x100000000ull;
constexpr uint64_t kVortexBarSize = 0x100000000ull;

struct Region {
    const char *name;
    uint64_t base;
    uint64_t size;
    bool is_dram;
};
constexpr Region kRegions[] = {
    {"vortex_cp", kVortexCpBase, kVortexCpSize, false},
    {"host_heap", kHostHeapBase, kHostHeapSize, false},
    {"vortex_bar", kVortexBarBase, kVortexBarSize, true},
};
constexpr size_t kNumRegions = sizeof(kRegions) / sizeof(kRegions[0]);

inline const char *RegionOf(uint64_t addr) {
    for (const auto &region : kRegions)
        if (addr >= region.base && addr - region.base < region.size)
            return region.name;
    return nullptr;
}
inline bool IsTraced(uint64_t addr) {
    return addr >= kVortexBarBase && addr - kVortexBarBase < kVortexBarSize;
}
} // namespace hettrace
#endif // HETTRACE_ADDRMAP_H_
