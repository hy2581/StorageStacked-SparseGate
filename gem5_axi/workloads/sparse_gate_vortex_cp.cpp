// Host configures Vortex's command processor; its DMA master issues every
// SparseGate upload, register access and result read over native AXI/UCIe.
#include <vortex2.h>
#include "../../research/fixtures/system_smoke.h"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

namespace {
constexpr uint64_t kDeviceBase = 0x90000000ull;
constexpr uint64_t kPhysicalBase = 0x190000000ull;
constexpr uint64_t kWindowBytes = 0x100000ull;
constexpr uint64_t kRegs = 0xf0000ull;
constexpr uint64_t kQ = 0x10000ull, kK = 0x14000ull, kKv = 0x20000ull;
constexpr uint64_t kOut = 0x30000ull, kGather = 0x34000ull;

void require(vx_result_t result, const char* action) {
    if (result != VX_SUCCESS) {
        std::fprintf(stderr, "VORTEX SPARSE GATE FAIL %s: %s\n", action,
                     vx_result_string(result));
        std::exit(2);
    }
}
class Client {
    vx_device_h device_ = nullptr;
    vx_queue_h queue_ = nullptr;
    vx_buffer_h aperture_ = nullptr;
public:
    Client() {
        require(vx_device_open(0, &device_), "open");
        vx_queue_info_t info = {sizeof(info), nullptr, VX_QUEUE_PRIORITY_NORMAL, 0};
        require(vx_queue_create(device_, &info, &queue_), "queue");
        require(vx_buffer_reserve(device_, kDeviceBase, kWindowBytes,
                                  VX_MEM_READ_WRITE, &aperture_), "reserve aperture");
        uint64_t addr = 0;
        require(vx_buffer_address(aperture_, &addr), "buffer address");
        if (addr != kDeviceBase) { std::fputs("VORTEX SPARSE GATE FAIL address\n", stderr); std::exit(2); }
    }
    ~Client() {
        if (aperture_) vx_buffer_release(aperture_);
        if (queue_) vx_queue_release(queue_);
        if (device_) vx_device_release(device_);
    }
    void write(uint64_t off, const void* data, uint64_t size) {
        if (off+size > kWindowBytes) std::abort();
        require(vx_enqueue_write(queue_, aperture_, off, data, size, 0, nullptr, nullptr), "CP write");
        require(vx_queue_finish(queue_, UINT64_MAX), "CP write completion");
    }
    void read(uint64_t off, void* data, uint64_t size) {
        if (off+size > kWindowBytes) std::abort();
        require(vx_enqueue_read(queue_, data, aperture_, off, size, 0, nullptr, nullptr), "CP read");
        require(vx_queue_finish(queue_, UINT64_MAX), "CP read completion");
    }
    void wr(uint64_t off, uint32_t value) { write(kRegs+off, &value, sizeof(value)); }
    uint32_t rd(uint64_t off) { uint32_t value = 0; read(kRegs+off, &value, sizeof(value)); return value; }
    void address(uint64_t off, uint64_t value) { wr(off, uint32_t(value)); wr(off+4, uint32_t(value>>32)); }
};

uint8_t kv_byte(unsigned key, unsigned byte) { return uint8_t(key*37u+byte*13u+9u); }
uint32_t le32(const uint8_t* p) {
    return uint32_t(p[0]) | uint32_t(p[1])<<8 | uint32_t(p[2])<<16 | uint32_t(p[3])<<24;
}
}

int main() {
    Client c;
    if (c.rd(0) != 0x53474154u) { std::fputs("VORTEX SPARSE GATE FAIL id\n", stderr); return 3; }
    c.write(kQ, sg_fixture_q, sizeof(sg_fixture_q));
    c.write(kK, sg_fixture_k, sizeof(sg_fixture_k));
    std::vector<uint8_t> kv(SG_FIX_NKEYS*SG_FIX_KV_BYTES);
    for (unsigned key=0; key<SG_FIX_NKEYS; ++key)
        for (unsigned byte=0; byte<SG_FIX_KV_BYTES; ++byte)
            kv[key*SG_FIX_KV_BYTES+byte] = kv_byte(key,byte);
    c.write(kKv, kv.data(), kv.size());
    c.address(0x10, kPhysicalBase+kQ); c.address(0x18, kPhysicalBase+kK);
    c.address(0x20, kPhysicalBase+0x18000);
    c.address(0x28, kPhysicalBase+kOut); c.address(0x30, kPhysicalBase+kKv);
    c.address(0x38, kPhysicalBase+kGather);
    c.wr(0x40, SG_FIX_NKEYS); c.wr(0x44, SG_FIX_NCAND);
    c.wr(0x48, SG_FIX_TOPK); c.wr(0x4c, SG_FIX_HEADS);
    c.wr(0x50, 0x51a7u); c.wr(0x54, 7); c.wr(0x58, SG_FIX_KV_BYTES);
    c.wr(0x0c, 0); c.wr(0x08, 1);
    uint32_t status = 0;
    for (unsigned poll=0; poll<200000; ++poll) {
        status = c.rd(0x04);
        if (!(status&1u) && (status&6u)) break;
    }
    const uint32_t count=c.rd(0x5c), cycles=c.rd(0x60);
    const uint32_t reads=c.rd(0x68), writes=c.rd(0x6c), scores=c.rd(0x70);
    if (status!=2 || count!=SG_FIX_TOPK || scores!=SG_FIX_NKEYS ||
        reads!=3*SG_FIX_HEADS+3*SG_FIX_NKEYS+SG_FIX_TOPK*9 ||
        writes!=SG_FIX_TOPK*10 || c.rd(0x74)!=1) {
        std::fprintf(stderr,"VORTEX SPARSE GATE FAIL status=%u count=%u scores=%u reads=%u writes=%u\n",
                     status,count,scores,reads,writes);
        return 4;
    }
    std::vector<uint8_t> result(SG_FIX_TOPK*32), gather(SG_FIX_TOPK*SG_FIX_KV_BYTES);
    c.read(kOut,result.data(),result.size()); c.read(kGather,gather.data(),gather.size());
    for (unsigned i=0; i<SG_FIX_TOPK; ++i) {
        const uint8_t* p=result.data()+i*32;
        if (le32(p)!=sg_fixture_full_index[i] || le32(p+4)!=sg_fixture_full_score[i]) {
            std::fprintf(stderr,"VORTEX SPARSE GATE FAIL result %u\n",i); return 5;
        }
        for (unsigned j=8; j<32; ++j) if (p[j]) return 6;
        for (unsigned j=0; j<SG_FIX_KV_BYTES; ++j)
            if (gather[i*SG_FIX_KV_BYTES+j]!=kv_byte(sg_fixture_full_index[i],j)) return 7;
    }
    std::printf("VORTEX_GATE_COMMAND mode=0 status=%u count=%u scores=%u read_beats=%u write_beats=%u cycles=%u\n",
                status,count,scores,reads,writes,cycles);
    std::printf("VORTEX SPARSE GATE PASS source=Vortex-CP-DMA heads=%u keys=%u topk=%u gather_bytes=%u\n",
                SG_FIX_HEADS,SG_FIX_NKEYS,SG_FIX_TOPK,SG_FIX_TOPK*SG_FIX_KV_BYTES);
    return 0;
}
