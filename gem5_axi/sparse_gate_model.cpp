#include "sparse_gate_abi.h"
#include "Vsparse_gate_axi.h"
#include "verilated.h"
#include "verilated_vcd_c.h"
#include "sparse_gate_build_id.h"
#include <exception>
#include <memory>
#include <stdexcept>
#include <string>

namespace {
struct Model {
    VerilatedContext context;
    std::unique_ptr<Vsparse_gate_axi> rtl;
    std::unique_ptr<VerilatedVcdC> trace;
    std::string error;
    uint64_t last_time = 0;
    Model() {
        context.threads(1);
        context.randReset(0);
        context.traceEverOn(true);
        rtl = std::make_unique<Vsparse_gate_axi>(&context, "sparse_gate");
    }
};
}
extern "C" uint32_t sparse_gate_abi_version() { return SPARSE_GATE_ABI_VERSION; }
extern "C" uint32_t sparse_gate_input_size() { return sizeof(SparseGateInputs); }
extern "C" uint32_t sparse_gate_output_size() { return sizeof(SparseGateOutputs); }
extern "C" const char *sparse_gate_build_id() { return SPARSE_GATE_BUILD_ID; }
extern "C" void *sparse_gate_create() { try { return new Model; } catch (...) { return nullptr; } }
extern "C" int sparse_gate_trace_open(void *p, const char *path) {
    if (!p || !path) return -1;
    auto& m=*static_cast<Model *>(p);
    try {
        if (m.trace) throw std::runtime_error("trace already open");
        m.trace=std::make_unique<VerilatedVcdC>();
        m.rtl->trace(m.trace.get(),1); m.trace->open(path);
        if (!m.trace->isOpen()) throw std::runtime_error("cannot open RTL VCD");
        return 0;
    } catch (const std::exception& e) { m.error=e.what(); return -1; }
}
extern "C" const char *sparse_gate_last_error(void *p) {
    return p ? static_cast<Model *>(p)->error.c_str() : "null model";
}
extern "C" void sparse_gate_trace_flush(void *p) {
    if(p){auto& m=*static_cast<Model *>(p);if(m.trace)m.trace->flush();}
}
extern "C" int sparse_gate_eval(void *p, const SparseGateInputs *in,
                                SparseGateOutputs *out, uint64_t time_fs) {
    if (!p || !in || !out) return -1;
    auto& m = *static_cast<Model *>(p);
    try {
        if (!m.error.empty()) return -1;
        if (time_fs < m.last_time) throw std::runtime_error("backward model time");
        const bool new_time=time_fs>m.last_time;
        m.last_time = time_fs; m.context.time(time_fs);
        auto& r = *m.rtl;
#define COPY_IN(n) r.n = in->n
        COPY_IN(clk); COPY_IN(rst_n);
        COPY_IN(s_axi_awaddr); COPY_IN(s_axi_awid); COPY_IN(s_axi_awlen);
        COPY_IN(s_axi_awsize); COPY_IN(s_axi_awburst); COPY_IN(s_axi_awvalid);
        COPY_IN(s_axi_wstrb); COPY_IN(s_axi_wlast); COPY_IN(s_axi_wvalid); COPY_IN(s_axi_bready);
        COPY_IN(s_axi_araddr); COPY_IN(s_axi_arid); COPY_IN(s_axi_arlen);
        COPY_IN(s_axi_arsize); COPY_IN(s_axi_arburst); COPY_IN(s_axi_arvalid); COPY_IN(s_axi_rready);
        COPY_IN(m_axi_awready); COPY_IN(m_axi_wready); COPY_IN(m_axi_bid);
        COPY_IN(m_axi_bresp); COPY_IN(m_axi_bvalid); COPY_IN(m_axi_arready);
        COPY_IN(m_axi_rid); COPY_IN(m_axi_rresp); COPY_IN(m_axi_rlast); COPY_IN(m_axi_rvalid);
#undef COPY_IN
        for (unsigned i=0; i<8; ++i) { r.s_axi_wdata[i]=in->s_axi_wdata[i]; r.m_axi_rdata[i]=in->m_axi_rdata[i]; }
        r.eval();
        if (m.trace && new_time) m.trace->dump(time_fs);
        if (m.context.gotFinish()) throw std::runtime_error("unexpected RTL finish");
        *out = {};
#define COPY_OUT(n) out->n = r.n
        COPY_OUT(s_axi_awready); COPY_OUT(s_axi_wready); COPY_OUT(s_axi_bid);
        COPY_OUT(s_axi_bresp); COPY_OUT(s_axi_bvalid); COPY_OUT(s_axi_arready);
        COPY_OUT(s_axi_rid); COPY_OUT(s_axi_rresp); COPY_OUT(s_axi_rlast); COPY_OUT(s_axi_rvalid);
        COPY_OUT(m_axi_awid); COPY_OUT(m_axi_awaddr); COPY_OUT(m_axi_awlen);
        COPY_OUT(m_axi_awsize); COPY_OUT(m_axi_awburst); COPY_OUT(m_axi_awvalid);
        COPY_OUT(m_axi_wstrb); COPY_OUT(m_axi_wlast); COPY_OUT(m_axi_wvalid); COPY_OUT(m_axi_bready);
        COPY_OUT(m_axi_arid); COPY_OUT(m_axi_araddr); COPY_OUT(m_axi_arlen);
        COPY_OUT(m_axi_arsize); COPY_OUT(m_axi_arburst); COPY_OUT(m_axi_arvalid); COPY_OUT(m_axi_rready);
#undef COPY_OUT
        for (unsigned i=0; i<8; ++i) { out->s_axi_rdata[i]=r.s_axi_rdata[i]; out->m_axi_wdata[i]=r.m_axi_wdata[i]; }
        return 0;
    } catch (const std::exception& e) { m.error=e.what(); return -1; }
      catch (...) { m.error="unknown model exception"; return -1; }
}
extern "C" void sparse_gate_destroy(void *p) {
    if (p) { auto *m=static_cast<Model *>(p); m->rtl->final(); if(m->trace)m->trace->close(); delete m; }
}
