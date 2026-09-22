#ifndef STORAGESTACKED_SPARSE_GATE_ABI_H
#define STORAGESTACKED_SPARSE_GATE_ABI_H
/* No SystemC, C++ containers, scores or memory image cross this ABI. The caller
 * drives both clock edges at its existing global femtosecond timestamp. */
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define SPARSE_GATE_ABI_VERSION 0x00010000u
typedef struct SparseGateInputs {
    uint64_t s_axi_awaddr, s_axi_araddr;
    uint32_t s_axi_wdata[8], m_axi_rdata[8];
    uint32_t s_axi_wstrb;
    uint16_t s_axi_awid, s_axi_arid, m_axi_bid, m_axi_rid;
    uint8_t clk, rst_n;
    uint8_t s_axi_awlen, s_axi_awsize, s_axi_awburst, s_axi_awvalid;
    uint8_t s_axi_wlast, s_axi_wvalid, s_axi_bready;
    uint8_t s_axi_arlen, s_axi_arsize, s_axi_arburst, s_axi_arvalid, s_axi_rready;
    uint8_t m_axi_awready, m_axi_wready, m_axi_bresp, m_axi_bvalid;
    uint8_t m_axi_arready, m_axi_rresp, m_axi_rlast, m_axi_rvalid;
} SparseGateInputs;
typedef struct SparseGateOutputs {
    uint64_t m_axi_awaddr, m_axi_araddr;
    uint32_t s_axi_rdata[8], m_axi_wdata[8];
    uint32_t m_axi_wstrb;
    uint16_t s_axi_bid, s_axi_rid, m_axi_awid, m_axi_arid;
    uint8_t s_axi_awready, s_axi_wready, s_axi_bresp, s_axi_bvalid;
    uint8_t s_axi_arready, s_axi_rresp, s_axi_rlast, s_axi_rvalid;
    uint8_t m_axi_awlen, m_axi_awsize, m_axi_awburst, m_axi_awvalid;
    uint8_t m_axi_wlast, m_axi_wvalid, m_axi_bready;
    uint8_t m_axi_arlen, m_axi_arsize, m_axi_arburst, m_axi_arvalid, m_axi_rready;
} SparseGateOutputs;
uint32_t sparse_gate_abi_version(void);
uint32_t sparse_gate_input_size(void);
uint32_t sparse_gate_output_size(void);
const char *sparse_gate_build_id(void);
void *sparse_gate_create(void);
int sparse_gate_trace_open(void *, const char *path);
void sparse_gate_trace_flush(void *);
/* Nonzero signals a model failure; no subsequent result is acceptable. */
int sparse_gate_eval(void *, const SparseGateInputs *, SparseGateOutputs *, uint64_t time_fs);
const char *sparse_gate_last_error(void *);
void sparse_gate_destroy(void *);
#ifdef __cplusplus
}
#endif
#endif
