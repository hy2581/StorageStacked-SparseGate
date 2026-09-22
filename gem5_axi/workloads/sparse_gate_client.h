#ifndef SPARSE_GATE_CLIENT_H
#define SPARSE_GATE_CLIENT_H
/* Shared freestanding CPU/C++ client. All target bytes use volatile accesses;
 * no model, private memory image or software scoring occurs in this driver. */
#include <stdint.h>
#ifdef SG_USE_REAL_FIXTURE
#include "../../research/fixtures/csa2_real_weights_fixture.h"
#define SG_HEADS SG_REAL_HEADS
#define SG_NKEYS SG_REAL_KEYS
#define SG_TOPK SG_REAL_TOPK
#define SG_NCAND SG_REAL_NCAND
#define SG_Q ((const uint8_t *)sg_real_q)
#define SG_K ((const uint8_t *)sg_real_k)
#define SG_FULL_INDEX sg_real_expected_index
#define SG_FULL_SCORE sg_real_expected_score
#define SG_CAND sg_real_candidate_ids
#define SG_RE_INDEX sg_real_reindex_expected_index
#define SG_RE_SCORE sg_real_reindex_expected_score
#else
#include "../../research/fixtures/system_smoke.h"
#define SG_HEADS SG_FIX_HEADS
#define SG_NKEYS SG_FIX_NKEYS
#define SG_TOPK SG_FIX_TOPK
#define SG_NCAND SG_FIX_NCAND
#define SG_Q sg_fixture_q
#define SG_K sg_fixture_k
#define SG_FULL_INDEX sg_fixture_full_index
#define SG_FULL_SCORE sg_fixture_full_score
#define SG_CAND sg_fixture_candidates
#define SG_RE_INDEX sg_fixture_reindex_index
#define SG_RE_SCORE sg_fixture_reindex_score
#endif
#define SG_MMIO UINT64_C(0x900f0000)
#define SG_Q_ADDR UINT64_C(0x90010000)
#define SG_K_ADDR UINT64_C(0x90014000)
#define SG_C_ADDR UINT64_C(0x90018000)
#define SG_KV_ADDR UINT64_C(0x90020000)
#define SG_OUT_ADDR UINT64_C(0x90030000)
#define SG_GATHER_ADDR UINT64_C(0x90034000)
#define SG_OUT_REUSE UINT64_C(0x90038000)
#define SG_GATHER_REUSE UINT64_C(0x9003c000)
#define SG_KV_BYTES 288u
typedef struct SgCommandReport {
    uint32_t mode,status,count,scores,read_beats,write_beats,cycles;
} SgCommandReport;
typedef struct SgReport { SgCommandReport commands[5]; uint32_t failed_stage; } SgReport;
static inline void sg_wr(unsigned off,uint32_t value) {
    *(volatile uint32_t *)(uintptr_t)(SG_MMIO+off)=value;
}
static inline uint32_t sg_rd(unsigned off) {
    return *(volatile uint32_t *)(uintptr_t)(SG_MMIO+off);
}
static inline void sg_addr(unsigned off,uint64_t addr) {
    sg_wr(off,(uint32_t)addr);sg_wr(off+4,(uint32_t)(addr>>32));
}
static inline uint64_t sg_pack(const uint8_t *p) {
    uint64_t v=0;for(unsigned i=0;i<8;++i)v|=(uint64_t)p[i]<<(8*i);return v;
}
static inline uint8_t sg_kv_byte(unsigned key,unsigned byte) {
    return (uint8_t)(key*37u+byte*13u+9u);
}
static inline uint64_t sg_kv_word(unsigned key,unsigned byte) {
    uint64_t v=0;for(unsigned i=0;i<8;++i)v|=(uint64_t)sg_kv_byte(key,byte+i)<<(8*i);return v;
}
static inline void sg_upload(uint64_t addr,const uint8_t *p,unsigned count) {
    volatile uint64_t *dst=(volatile uint64_t *)(uintptr_t)addr;
    for(unsigned i=0;i<count;i+=8)dst[i/8]=sg_pack(p+i);
}
static inline int sg_command(SgCommandReport *r,unsigned mode,unsigned expected_error) {
    sg_wr(0x0c,mode);sg_wr(0x08,1);
    uint32_t status=0;
    for(unsigned i=0;i<200000;++i) {
        status=sg_rd(0x04);
        if(!(status&1u)&&(status&6u))break;
    }
    r->mode=mode;r->status=status;r->count=sg_rd(0x5c);r->cycles=sg_rd(0x60);
    r->read_beats=sg_rd(0x68);r->write_beats=sg_rd(0x6c);r->scores=sg_rd(0x70);
    if(status&1u)return 1;
    if(expected_error)return ((status&7u)!=4u||(status>>8)!=expected_error||sg_rd(0x74)!=0)?2:0;
    return ((status&7u)!=2u||status>>8||r->count!=SG_TOPK||sg_rd(0x74)!=1)?3:0;
}
static inline int sg_verify(uint64_t output,uint64_t gather,const uint32_t *idx,const uint32_t *score) {
    volatile const uint64_t *r=(volatile const uint64_t *)(uintptr_t)output;
    volatile const uint64_t *g=(volatile const uint64_t *)(uintptr_t)gather;
    for(unsigned i=0;i<SG_TOPK;++i) {
        if(r[4*i]!=((uint64_t)score[i]<<32|idx[i]))return 1;
        for(unsigned j=1;j<4;++j)if(r[4*i+j]!=0)return 2;
        for(unsigned byte=0;byte<SG_KV_BYTES;byte+=8)
            if(g[(i*SG_KV_BYTES+byte)/8]!=sg_kv_word(idx[i],byte))return 3;
    }
    return 0;
}
static inline int sg_acceptance(SgReport *report) {
#define SG_CHECK(stage,condition) do {if(!(condition)){report->failed_stage=(stage);return (stage);}}while(0)
    report->failed_stage=0;
    SG_CHECK(1,sg_rd(0)==0x53474154u);
    sg_upload(SG_Q_ADDR,SG_Q,SG_HEADS*96u);sg_upload(SG_K_ADDR,SG_K,SG_NKEYS*96u);
    volatile uint64_t *kv=(volatile uint64_t *)(uintptr_t)SG_KV_ADDR;
    for(unsigned key=0;key<SG_NKEYS;++key)
        for(unsigned byte=0;byte<SG_KV_BYTES;byte+=8)kv[(key*SG_KV_BYTES+byte)/8]=sg_kv_word(key,byte);
    volatile uint32_t *cand=(volatile uint32_t *)(uintptr_t)SG_C_ADDR;
    for(unsigned i=0;i<(SG_NCAND+7u)/8u*8u;++i)cand[i]=i<SG_NCAND?SG_CAND[i]:0;
    sg_addr(0x10,SG_Q_ADDR);sg_addr(0x18,SG_K_ADDR);sg_addr(0x20,SG_C_ADDR);
    sg_addr(0x28,SG_OUT_ADDR);sg_addr(0x30,SG_KV_ADDR);sg_addr(0x38,SG_GATHER_ADDR);
    sg_wr(0x40,SG_NKEYS);sg_wr(0x44,SG_NCAND);sg_wr(0x48,SG_TOPK);sg_wr(0x4c,SG_HEADS);
    sg_wr(0x50,0x51a7u);sg_wr(0x54,7);sg_wr(0x58,SG_KV_BYTES);
    SG_CHECK(2,sg_command(&report->commands[0],0,0)==0);
    SG_CHECK(3,sg_verify(SG_OUT_ADDR,SG_GATHER_ADDR,SG_FULL_INDEX,SG_FULL_SCORE)==0);
    SG_CHECK(4,report->commands[0].scores==SG_NKEYS&&report->commands[0].read_beats==3u*SG_HEADS+3u*SG_NKEYS+SG_TOPK*9u&&report->commands[0].write_beats==SG_TOPK*10u);
    /* A distinct output proves cached selection is actually emitted again. */
    sg_addr(0x28,SG_OUT_REUSE);sg_addr(0x38,SG_GATHER_REUSE);
    SG_CHECK(5,sg_command(&report->commands[1],2,0)==0);
    SG_CHECK(6,sg_verify(SG_OUT_REUSE,SG_GATHER_REUSE,SG_FULL_INDEX,SG_FULL_SCORE)==0);
    SG_CHECK(7,report->commands[1].scores==0&&report->commands[1].read_beats==SG_TOPK*9u&&report->commands[1].write_beats==SG_TOPK*10u);
    sg_addr(0x28,SG_OUT_ADDR);sg_addr(0x38,SG_GATHER_ADDR);sg_wr(0x54,8);
    SG_CHECK(8,sg_command(&report->commands[2],1,0)==0);
    SG_CHECK(9,sg_verify(SG_OUT_ADDR,SG_GATHER_ADDR,SG_RE_INDEX,SG_RE_SCORE)==0);
    SG_CHECK(10,report->commands[2].scores==SG_NCAND&&report->commands[2].read_beats==3u*SG_HEADS+3u*SG_NCAND+(SG_NCAND+7u)/8u+SG_TOPK*9u&&report->commands[2].write_beats==SG_TOPK*10u);
    sg_wr(0x54,9);
    SG_CHECK(11,sg_command(&report->commands[3],2,2)==0);
    SG_CHECK(12,report->commands[3].scores==0&&report->commands[3].read_beats==0&&report->commands[3].write_beats==0);
    SG_CHECK(13,sg_command(&report->commands[4],0,0)==0);
    SG_CHECK(14,sg_verify(SG_OUT_ADDR,SG_GATHER_ADDR,SG_FULL_INDEX,SG_FULL_SCORE)==0);
    SG_CHECK(15,report->commands[4].scores==SG_NKEYS&&report->commands[4].read_beats==3u*SG_HEADS+3u*SG_NKEYS+SG_TOPK*9u&&report->commands[4].write_beats==SG_TOPK*10u);
    return 0;
#undef SG_CHECK
}
#endif
