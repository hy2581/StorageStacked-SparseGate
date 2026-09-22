/* Independent freestanding x86-64 gem5 guest: FULL then REUSE, H32/N640/K512.
 * Inputs use real CSA2 layer20 weights and seeded RANDOM intermediate activations.
 * They are not text-derived model traces. The guest performs no score calculation.
 * Main KV is an opaque deterministic byte pattern, not a quantized model trace.
 * Every remote upload/readback is an aligned volatile uint64_t access; COMMAND
 * is a separate volatile uint32_t write. The same SE write/exit syscalls as the
 * small acceptance guest print results and terminate the simulated process.
 */
#include <stdint.h>
#include "../../research/fixtures/csa2_top512_fixture.h"

#define MMIO_ADDR UINT64_C(0x900f0000)
#define Q_ADDR UINT64_C(0x90010000)
#define K_ADDR UINT64_C(0x90012000)
#define KV_ADDR UINT64_C(0x90030000)
#define OUT_ADDR UINT64_C(0x90060000)
#define GATHER_ADDR UINT64_C(0x90070000)
#define REUSE_OUT_ADDR UINT64_C(0x900a0000)
#define REUSE_GATHER_ADDR UINT64_C(0x900b0000)
#define KV_BYTES 288u
#define RECORD_BYTES 96u
#define RESULT_BYTES 32u
#define POLL_LIMIT 2000000u

/* C99 compile-time checks keep the declared regions within the 1 MiB aperture. */
typedef char check_model_shape[(SG_LARGE_HEADS==32 && SG_LARGE_KEYS==640 && SG_LARGE_TOPK==512)?1:-1];
typedef char check_q_region[(Q_ADDR+SG_LARGE_HEADS*RECORD_BYTES<=K_ADDR)?1:-1];
typedef char check_k_region[(K_ADDR+SG_LARGE_KEYS*RECORD_BYTES<=KV_ADDR)?1:-1];
typedef char check_kv_region[(KV_ADDR+SG_LARGE_KEYS*KV_BYTES<=OUT_ADDR)?1:-1];
typedef char check_out_region[(OUT_ADDR+SG_LARGE_TOPK*RESULT_BYTES<=GATHER_ADDR)?1:-1];
typedef char check_gather_region[(GATHER_ADDR+SG_LARGE_TOPK*KV_BYTES<=REUSE_OUT_ADDR)?1:-1];
typedef char check_reuse_out_region[(REUSE_OUT_ADDR+SG_LARGE_TOPK*RESULT_BYTES<=REUSE_GATHER_ADDR)?1:-1];
typedef char check_reuse_gather_region[(REUSE_GATHER_ADDR+SG_LARGE_TOPK*KV_BYTES<=MMIO_ADDR)?1:-1];

typedef struct CommandReport {
    uint32_t mode,status,count,scores,read_beats,write_beats,cycles;
} CommandReport;

static long call3(long n,long a,long b,long c) {
    long r;
    __asm__ volatile("syscall":"=a"(r):"a"(n),"D"(a),"S"(b),"d"(c):"rcx","r11","memory");
    return r;
}
static void emit(const char *s) {
    unsigned n=0;while(s[n])++n;call3(1,1,(long)s,n);
}
static void number(uint32_t value) {
    char buf[11];unsigned n=0;
    do {buf[n++]=(char)('0'+value%10u);value/=10u;} while(value);
    for(unsigned i=0;i<n/2u;++i){char c=buf[i];buf[i]=buf[n-1u-i];buf[n-1u-i]=c;}
    call3(1,1,(long)buf,n);
}
static void reg_write(unsigned offset,uint32_t value) {
    *(volatile uint32_t *)(uintptr_t)(MMIO_ADDR+offset)=value;
}
static uint32_t reg_read(unsigned offset) {
    return *(volatile const uint32_t *)(uintptr_t)(MMIO_ADDR+offset);
}
static void address_write(unsigned offset,uint64_t value) {
    reg_write(offset,(uint32_t)value);reg_write(offset+4u,(uint32_t)(value>>32));
}
static uint64_t pack_word(const uint8_t *p) {
    uint64_t value=0;
    for(unsigned i=0;i<8u;++i)value|=(uint64_t)p[i]<<(8u*i);
    return value;
}
static uint8_t sg_kv_byte(unsigned key,unsigned byte) {
    return (uint8_t)(key*37u+byte*13u+9u);
}
static uint64_t kv_word(unsigned key,unsigned byte) {
    uint64_t value=0;
    for(unsigned i=0;i<8u;++i)value|=(uint64_t)sg_kv_byte(key,byte+i)<<(8u*i);
    return value;
}
static void upload(uint64_t address,const uint8_t *data,unsigned count) {
    volatile uint64_t *dst=(volatile uint64_t *)(uintptr_t)address;
    for(unsigned i=0;i<count;i+=8u)dst[i/8u]=pack_word(data+i);
}
static int command(CommandReport *r,unsigned mode) {
    reg_write(0x0c,mode);reg_write(0x08,1);
    uint32_t status=0;unsigned polls;
    for(polls=0;polls<POLL_LIMIT;++polls) {
        status=reg_read(0x04);
        if(!(status&1u) && (status&6u))break;
    }
    r->mode=mode;r->status=status;r->count=reg_read(0x5c);r->scores=reg_read(0x70);
    r->cycles=reg_read(0x60);r->read_beats=reg_read(0x68);r->write_beats=reg_read(0x6c);
    if(polls==POLL_LIMIT)return 1;
    if(status!=2u || r->count!=SG_LARGE_TOPK || reg_read(0x74)!=1u)return 2;
    /* The output format reports low32 cycles; reject overflow instead of hiding it. */
    if(reg_read(0x64)!=0u || r->cycles==0u)return 3;
    return 0;
}
static int verify_output(uint64_t output,uint64_t gather) {
    volatile const uint64_t *r=(volatile const uint64_t *)(uintptr_t)output;
    volatile const uint64_t *g=(volatile const uint64_t *)(uintptr_t)gather;
    for(unsigned i=0;i<SG_LARGE_TOPK;++i) {
        const uint32_t index=sg_large_expected_index[i];
        const uint32_t score=sg_large_expected_score[i];
        if(r[4u*i]!=((uint64_t)score<<32 | index))return 1;
        for(unsigned word=1;word<4u;++word)if(r[4u*i+word]!=0u)return 2;
        for(unsigned byte=0;byte<KV_BYTES;byte+=8u)
            if(g[(i*KV_BYTES+byte)/8u]!=kv_word(index,byte))return 3;
    }
    return 0;
}
static int acceptance(CommandReport *reports) {
    if(reg_read(0)!=0x53474154u)return 1;
    upload(Q_ADDR,(const uint8_t *)sg_large_q,SG_LARGE_HEADS*RECORD_BYTES);
    upload(K_ADDR,(const uint8_t *)sg_large_k,SG_LARGE_KEYS*RECORD_BYTES);
    volatile uint64_t *kv=(volatile uint64_t *)(uintptr_t)KV_ADDR;
    for(unsigned key=0;key<SG_LARGE_KEYS;++key)
        for(unsigned byte=0;byte<KV_BYTES;byte+=8u)
            kv[(key*KV_BYTES+byte)/8u]=kv_word(key,byte);
    address_write(0x10,Q_ADDR);address_write(0x18,K_ADDR);address_write(0x20,0);
    address_write(0x28,OUT_ADDR);address_write(0x30,KV_ADDR);address_write(0x38,GATHER_ADDR);
    reg_write(0x40,SG_LARGE_KEYS);reg_write(0x44,0);reg_write(0x48,SG_LARGE_TOPK);
    reg_write(0x4c,SG_LARGE_HEADS);reg_write(0x50,0x512c5a2u);reg_write(0x54,7);
    reg_write(0x58,KV_BYTES);
    if(command(&reports[0],0)!=0)return 2;
    if(verify_output(OUT_ADDR,GATHER_ADDR)!=0)return 3;
    if(reports[0].scores!=SG_LARGE_KEYS ||
       reports[0].read_beats!=3u*SG_LARGE_HEADS+3u*SG_LARGE_KEYS+SG_LARGE_TOPK*(KV_BYTES/32u) ||
       reports[0].write_beats!=SG_LARGE_TOPK*(1u+KV_BYTES/32u))return 4;
    /* Distinct destinations demonstrate that REUSE emits and gathers again. */
    address_write(0x28,REUSE_OUT_ADDR);address_write(0x38,REUSE_GATHER_ADDR);
    if(command(&reports[1],2)!=0)return 5;
    if(verify_output(REUSE_OUT_ADDR,REUSE_GATHER_ADDR)!=0)return 6;
    if(reports[1].scores!=0u || reports[1].read_beats!=SG_LARGE_TOPK*(KV_BYTES/32u) ||
       reports[1].write_beats!=SG_LARGE_TOPK*(1u+KV_BYTES/32u))return 7;
    return 0;
}
void _start(void) {
    CommandReport reports[2]={{0},{0}};
    int code=acceptance(reports);
    if(code) {
        emit("CPU SPARSE GATE TOP512 FAIL stage=");number((uint32_t)code);emit("\n");
    } else {
        for(unsigned i=0;i<2u;++i) {
            const CommandReport *c=&reports[i];
            emit("GATE_COMMAND mode=");number(c->mode);emit(" status=");number(c->status);
            emit(" count=");number(c->count);emit(" scores=");number(c->scores);
            emit(" read_beats=");number(c->read_beats);emit(" write_beats=");number(c->write_beats);
            emit(" cycles=");number(c->cycles);emit("\n");
        }
        emit("CPU SPARSE GATE TOP512 PASS heads=");number(SG_LARGE_HEADS);
        emit(" keys=");number(SG_LARGE_KEYS);emit(" topk=");number(SG_LARGE_TOPK);
        emit(" commands=2 errors_expected=0 gather_bytes=288\n");
    }
    call3(60,code,0,0);__builtin_unreachable();
}
