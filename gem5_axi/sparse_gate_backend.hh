#pragma once
#include "simple_mem_if.h"
#include <memory>
#include <string>

namespace storage_axi {
/* A bounded routing/handshake adapter, not an attention implementation. */
class SparseGateBackend : public sc_core::sc_module {
  public:
    sc_core::sc_in<bool> clk{"clk"}, resetn{"resetn"};
    sc_core::sc_fifo_in<SimpleMemRequest> host_request{"host_request"};
    sc_core::sc_fifo_out<SimpleMemResponse> host_response{"host_response"};
    sc_core::sc_fifo_out<SimpleMemRequest> memory_request{"memory_request"};
    sc_core::sc_fifo_in<SimpleMemResponse> memory_response{"memory_response"};
    SC_HAS_PROCESS(SparseGateBackend);
    SparseGateBackend(sc_core::sc_module_name, const std::string& library,
                      uint64_t mmio_base, const std::string& trace_dir);
    ~SparseGateBackend();
    void finish();
  private:
    struct State;
    std::unique_ptr<State> state;
    void edge();
};
}
