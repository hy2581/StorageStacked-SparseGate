// Vortex CP DMA online acceptance with the fixed H32/N640/K512 CSA2 fixture.
// Weights are trained; intermediate activations are seeded synthetic inputs.
#include <vortex2.h>
#include "../../research/fixtures/csa2_top512_fixture.h"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>

namespace {
constexpr uint64_t kDeviceBase=0x90000000ull;
constexpr uint64_t kPhysicalBase=0x190000000ull;
constexpr uint64_t kWindowBytes=0x100000ull;
constexpr uint64_t kRegs=0xf0000ull;
constexpr uint64_t kQ=0x10000ull,kK=0x12000ull,kKv=0x24000ull;
constexpr uint64_t kOut=0x53000ull,kGather=0x59000ull;
constexpr unsigned kKvBytes=288;

void require(vx_result_t value,const char* operation) {
    if(value!=VX_SUCCESS) {
        std::fprintf(stderr,"VORTEX LONG GATE FAIL %s: %s\n",operation,vx_result_string(value));
        std::exit(2);
    }
}
class Client {
    vx_device_h device_=nullptr;
    vx_queue_h queue_=nullptr;
    vx_buffer_h aperture_=nullptr;
public:
    Client() {
        require(vx_device_open(0,&device_),"open");
        vx_queue_info_t info={sizeof(info),nullptr,VX_QUEUE_PRIORITY_NORMAL,0};
        require(vx_queue_create(device_,&info,&queue_),"queue");
        require(vx_buffer_reserve(device_,kDeviceBase,kWindowBytes,VX_MEM_READ_WRITE,&aperture_),"reserve");
        uint64_t address=0;
        require(vx_buffer_address(aperture_,&address),"address");
        if(address!=kDeviceBase) std::abort();
    }
    ~Client() {
        if(aperture_) vx_buffer_release(aperture_);
        if(queue_) vx_queue_release(queue_);
        if(device_) vx_device_release(device_);
    }
    void transfer(uint64_t off,void* data,uint64_t bytes,bool is_write) {
        if(off+bytes>kWindowBytes) std::abort();
        auto* p=static_cast<uint8_t*>(data);
        for(uint64_t pos=0;pos<bytes;pos+=4096) {
            const uint64_t n=(bytes-pos<4096)?bytes-pos:4096;
            if(is_write) require(vx_enqueue_write(queue_,aperture_,off+pos,p+pos,n,0,nullptr,nullptr),"CP write");
            else require(vx_enqueue_read(queue_,p+pos,aperture_,off+pos,n,0,nullptr,nullptr),"CP read");
            require(vx_queue_finish(queue_,UINT64_MAX),"CP completion");
        }
    }
    void write(uint64_t off,const void* data,uint64_t bytes) {
        transfer(off,const_cast<void*>(data),bytes,true);
    }
    void read(uint64_t off,void* data,uint64_t bytes) {transfer(off,data,bytes,false);}
    void wr(uint64_t off,uint32_t value) {write(kRegs+off,&value,sizeof(value));}
    uint32_t rd(uint64_t off) {uint32_t value=0;read(kRegs+off,&value,sizeof(value));return value;}
    void address(uint64_t off,uint64_t value) {wr(off,uint32_t(value));wr(off+4,uint32_t(value>>32));}
};
uint8_t kv_byte(unsigned key,unsigned byte) {return uint8_t(key*37u+byte*13u+9u);}
uint32_t le32(const uint8_t* p) {
    return uint32_t(p[0])|(uint32_t(p[1])<<8)|(uint32_t(p[2])<<16)|(uint32_t(p[3])<<24);
}
}

int main() {
    static_assert(sizeof(sg_large_q)==SG_LARGE_HEADS*96u);
    static_assert(sizeof(sg_large_k)==SG_LARGE_KEYS*96u);
    static_assert(kQ+sizeof(sg_large_q)<=kK);
    static_assert(kK+sizeof(sg_large_k)<=kKv);
    static_assert(kKv+SG_LARGE_KEYS*kKvBytes<=kOut);
    static_assert(kOut+SG_LARGE_TOPK*32u<=kGather);
    static_assert(kGather+SG_LARGE_TOPK*kKvBytes<kRegs);
    Client c;
    if(c.rd(0)!=0x53474154u) return 3;
    c.write(kQ,sg_large_q,sizeof(sg_large_q));
    c.write(kK,sg_large_k,sizeof(sg_large_k));
    std::vector<uint8_t> kv(SG_LARGE_KEYS*kKvBytes);
    for(unsigned key=0;key<SG_LARGE_KEYS;++key)
        for(unsigned byte=0;byte<kKvBytes;++byte)
            kv[key*kKvBytes+byte]=kv_byte(key,byte);
    c.write(kKv,kv.data(),kv.size());
    c.address(0x10,kPhysicalBase+kQ);c.address(0x18,kPhysicalBase+kK);
    c.address(0x20,kPhysicalBase+0x22000);
    c.address(0x28,kPhysicalBase+kOut);c.address(0x30,kPhysicalBase+kKv);
    c.address(0x38,kPhysicalBase+kGather);
    c.wr(0x40,SG_LARGE_KEYS);c.wr(0x44,0);
    c.wr(0x48,SG_LARGE_TOPK);c.wr(0x4c,SG_LARGE_HEADS);
    c.wr(0x50,0x51a7u);c.wr(0x54,7);c.wr(0x58,kKvBytes);
    c.wr(0x0c,0);c.wr(0x08,1);
    uint32_t status=0;
    for(unsigned poll=0;poll<200000;++poll) {
        status=c.rd(0x04);
        if(!(status&1u)&&(status&6u)) break;
    }
    const uint32_t count=c.rd(0x5c),cycles=c.rd(0x60);
    const uint32_t reads=c.rd(0x68),writes=c.rd(0x6c),scores=c.rd(0x70);
    const uint32_t expected_reads=3*SG_LARGE_HEADS+3*SG_LARGE_KEYS+SG_LARGE_TOPK*(kKvBytes/32);
    const uint32_t expected_writes=SG_LARGE_TOPK*(1+kKvBytes/32);
    if(status!=2 || count!=SG_LARGE_TOPK || scores!=SG_LARGE_KEYS ||
       reads!=expected_reads || writes!=expected_writes || c.rd(0x74)!=1) {
        std::fprintf(stderr,"VORTEX LONG GATE FAIL status=%u count=%u scores=%u reads=%u writes=%u\n",
                     status,count,scores,reads,writes);
        return 4;
    }
    std::vector<uint8_t> result(SG_LARGE_TOPK*32u),gather(SG_LARGE_TOPK*kKvBytes);
    c.read(kOut,result.data(),result.size());c.read(kGather,gather.data(),gather.size());
    for(unsigned i=0;i<SG_LARGE_TOPK;++i) {
        const uint8_t* p=result.data()+i*32u;
        if(le32(p)!=sg_large_expected_index[i] || le32(p+4)!=sg_large_expected_score[i]) {
            std::fprintf(stderr,"VORTEX LONG GATE FAIL result %u\n",i);return 5;
        }
        for(unsigned j=8;j<32;++j) if(p[j]) return 6;
        for(unsigned j=0;j<kKvBytes;++j)
            if(gather[i*kKvBytes+j]!=kv_byte(sg_large_expected_index[i],j)) return 7;
    }
    std::printf("VORTEX_GATE_COMMAND mode=0 status=%u count=%u scores=%u read_beats=%u write_beats=%u cycles=%u\n",
                status,count,scores,reads,writes,cycles);
    std::printf("VORTEX SPARSE GATE PASS source=Vortex-CP-DMA heads=%u keys=%u topk=%u gather_bytes=%u\n",
                SG_LARGE_HEADS,SG_LARGE_KEYS,SG_LARGE_TOPK,SG_LARGE_TOPK*kKvBytes);
    return 0;
}
