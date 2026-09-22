// One-outstanding AXI256 DMA. Requests are accepted only when idle. Responses
// (including errors) retire exactly once; all five payloads hold under stalls.
module sparse_gate_dma #(
    parameter logic [63:0] MEM_BASE=64'h90000000,
    parameter logic [63:0] MEM_BYTES=64'h100000,
    parameter logic [63:0] REG_BASE=64'h900f0000
)(
 input logic clk, rst_n,
 input logic req_valid, req_write, output logic req_ready,
 input logic [63:0] req_addr, input logic [255:0] req_data,
 input logic [31:0] req_strb,
 output logic done, error, output logic [255:0] read_data,
 output logic [31:0] read_beats, write_beats,
 input logic clear_counts,
 output logic [15:0] m_axi_awid, output logic [63:0] m_axi_awaddr,
 output logic [7:0] m_axi_awlen, output logic [2:0] m_axi_awsize,
 output logic [1:0] m_axi_awburst, output logic m_axi_awvalid, input logic m_axi_awready,
 output logic [255:0] m_axi_wdata, output logic [31:0] m_axi_wstrb,
 output logic m_axi_wlast, m_axi_wvalid, input logic m_axi_wready,
 input logic [15:0] m_axi_bid, input logic [1:0] m_axi_bresp,
 input logic m_axi_bvalid, output logic m_axi_bready,
 output logic [15:0] m_axi_arid, output logic [63:0] m_axi_araddr,
 output logic [7:0] m_axi_arlen, output logic [2:0] m_axi_arsize,
 output logic [1:0] m_axi_arburst, output logic m_axi_arvalid, input logic m_axi_arready,
 input logic [15:0] m_axi_rid, input logic [255:0] m_axi_rdata,
 input logic [1:0] m_axi_rresp, input logic m_axi_rlast, m_axi_rvalid,
 output logic m_axi_rready
);
 typedef enum logic[2:0] {IDLE, WRITE, BRESP, READ, RRESP} state_t;
 state_t state; logic aw_sent,w_sent;
 assign req_ready=state==IDLE;
 assign m_axi_awid=16'd1; assign m_axi_arid=16'd1;
 assign m_axi_awlen=0; assign m_axi_arlen=0;
 assign m_axi_awsize=5; assign m_axi_arsize=5;
 assign m_axi_awburst=1; assign m_axi_arburst=1;
 assign m_axi_wlast=1;
 assign m_axi_awvalid=rst_n && state==WRITE && !aw_sent;
 assign m_axi_wvalid=rst_n && state==WRITE && !w_sent;
 assign m_axi_bready=rst_n && state==BRESP;
 assign m_axi_arvalid=rst_n && state==READ;
 assign m_axi_rready=rst_n && state==RRESP;
 always_ff @(posedge clk) begin
  if (!rst_n) begin
   state<=IDLE; done<=0; error<=0; aw_sent<=0;w_sent<=0;
   m_axi_awaddr<=0;m_axi_araddr<=0;m_axi_wdata<=0;m_axi_wstrb<=0;
   read_data<=0;read_beats<=0;write_beats<=0;
  end else begin
   done<=0;
   if(clear_counts) begin read_beats<=0;write_beats<=0;end
   case(state)
    IDLE: if(req_valid) begin
     error<=0;
     if(req_addr[4:0]!=0 || req_addr<MEM_BASE || req_addr>MEM_BASE+MEM_BYTES-32 ||
        (req_addr>=REG_BASE && req_addr<REG_BASE+4096)) begin done<=1;error<=1;end
     else if(req_write) begin
      m_axi_awaddr<=req_addr;m_axi_wdata<=req_data;m_axi_wstrb<=req_strb;
      aw_sent<=0;w_sent<=0;state<=WRITE;
     end else begin m_axi_araddr<=req_addr;state<=READ;end
    end
    WRITE: begin
     if(m_axi_awready && !aw_sent) aw_sent<=1;
     if(m_axi_wready && !w_sent) w_sent<=1;
     if((aw_sent||m_axi_awready)&&(w_sent||m_axi_wready)) state<=BRESP;
    end
    BRESP: if(m_axi_bvalid) begin
     done<=1;error<=m_axi_bresp!=0 || m_axi_bid!=1;write_beats<=write_beats+1;state<=IDLE;
    end
    READ: if(m_axi_arready) state<=RRESP;
    RRESP: if(m_axi_rvalid) begin
     read_data<=m_axi_rdata;read_beats<=read_beats+1;
     // Drain a malformed multi-beat response before reporting failure.
     if(m_axi_rresp!=0 || m_axi_rid!=1 || !m_axi_rlast) error<=1;
     if(m_axi_rlast) begin done<=1;state<=IDLE;end
    end
    default:state<=IDLE;
   endcase
  end
 end
endmodule
