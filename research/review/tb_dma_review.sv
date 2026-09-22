`timescale 1ns/1ps
module tb_dma_review;
 logic clk=0,rst_n=0;
 always #5 clk=~clk;
 logic req_valid=0,req_write=0,req_ready;
 logic [63:0] req_addr=0;logic [255:0] req_data=0;logic [31:0] req_strb=0;
 logic done,error;logic [255:0] read_data;logic [31:0] read_beats,write_beats;
 logic clear_counts=0;
 logic [15:0] m_axi_awid,m_axi_arid,m_axi_bid=0,m_axi_rid=0;
 logic [63:0] m_axi_awaddr,m_axi_araddr;
 logic [7:0] m_axi_awlen,m_axi_arlen;
 logic [2:0] m_axi_awsize,m_axi_arsize;
 logic [1:0] m_axi_awburst,m_axi_arburst,m_axi_bresp=0,m_axi_rresp=0;
 logic m_axi_awvalid,m_axi_awready=0,m_axi_arvalid,m_axi_arready=0;
 logic [255:0] m_axi_wdata,m_axi_rdata=0;
 logic [31:0] m_axi_wstrb;
 logic m_axi_wlast,m_axi_wvalid,m_axi_wready=0;
 logic m_axi_bvalid=0,m_axi_bready,m_axi_rlast=0,m_axi_rvalid=0,m_axi_rready;
 sparse_gate_dma dut(.*);
 integer cycles=0,done_count=0,error_count=0;
 always @(posedge clk) begin
  #1;cycles=cycles+1;
  if(rst_n && done)begin done_count=done_count+1;if(error)error_count=error_count+1;end
 end
 initial begin #100000;$fatal(1,"DMA review watchdog");end
 task automatic check(input logic ok,input string why);
  if(!ok)$fatal(1,"%s cycle=%0d",why,cycles);
 endtask
 task automatic start(input logic wr);
  @(negedge clk);check(req_ready,"request not idle after prior completion");
  req_valid=1;req_write=wr;req_addr=64'h90004000;req_data={8{32'h1234abcd}};req_strb=32'hff00ffff;
  @(posedge clk);#2;check(!error,"previous error not cleared on new request");
  @(negedge clk);req_valid=0;
 endtask
 task automatic read_address;
  check(m_axi_arvalid&&m_axi_arid==1&&m_axi_arlen==0&&m_axi_arsize==5&&m_axi_arburst==1,"read request geometry");
  m_axi_arready=1;@(posedge clk);#2;@(negedge clk);m_axi_arready=0;
  check(m_axi_rready,"not ready for read response");
 endtask
 task automatic read_reply(input logic [15:0] id,input logic [1:0] resp,
                            input logic last,input logic want_done,input logic want_error);
  m_axi_rvalid=1;m_axi_rid=id;m_axi_rresp=resp;m_axi_rlast=last;m_axi_rdata={8{32'hdeadbeef}};
  @(posedge clk);#2;check(done==want_done,"read completion/drain timing");check(error==want_error,"read error propagation");
  if(want_done)check(read_data=={8{32'hdeadbeef}},"read data changed");
  @(negedge clk);m_axi_rvalid=0;
 endtask
 task automatic valid_read;
  start(0);read_address();read_reply(1,0,1,1,0);
 endtask
 task automatic write_address_data;
  check(m_axi_awvalid&&m_axi_wvalid&&m_axi_awid==1&&m_axi_awlen==0&&m_axi_awsize==5&&m_axi_awburst==1,"write request geometry");
  m_axi_awready=1;m_axi_wready=0;
  @(posedge clk);#2;@(negedge clk);m_axi_awready=0;
  repeat(3)begin
   check(!m_axi_awvalid&&m_axi_wvalid&&m_axi_wlast&&m_axi_wdata=={8{32'h1234abcd}}&&m_axi_wstrb==32'hff00ffff,"AW/W independent or stalled W changed");
   check(!done&&!m_axi_bready,"premature write completion before W");
   @(posedge clk);#2;@(negedge clk);
  end
  m_axi_wready=1;@(posedge clk);#2;@(negedge clk);m_axi_wready=0;
  check(m_axi_bready,"not ready after AW and W");
 endtask
 task automatic write_reply(input logic [15:0] id,input logic [1:0] resp,input logic want_error);
  m_axi_bvalid=1;m_axi_bid=id;m_axi_bresp=resp;
  @(posedge clk);#2;check(done&&error==want_error,"write completion/error propagation");
  @(negedge clk);m_axi_bvalid=0;
 endtask
 task automatic valid_write;
  start(1);write_address_data();write_reply(1,0,0);
 endtask
 initial begin
  repeat(3)@(negedge clk);rst_n=1;
  start(0);read_address();read_reply(2,0,1,1,1);valid_read();
  $display("CHECK wrong_RID_then_read_recovery PASS");
  start(0);read_address();read_reply(1,0,0,0,1);
  repeat(4)begin
   check(m_axi_rready&&!done&&error,"malformed read not held/drained");
   @(posedge clk);#2;@(negedge clk);
  end
  read_reply(1,0,1,1,1);valid_read();
  $display("CHECK nonlast_R_then_last_R_drain_and_recovery PASS");
  start(1);write_address_data();write_reply(2,0,1);valid_write();
  $display("CHECK wrong_BID_then_write_recovery PASS");
  start(0);read_address();read_reply(1,2,1,1,1);valid_read();
  $display("CHECK RRESP_then_read_recovery PASS");
  start(1);write_address_data();write_reply(1,2,1);valid_write();
  $display("CHECK BRESP_then_write_recovery PASS");
  @(posedge clk);#2;
  check(done_count==10&&error_count==5,"completion/error count");
  check(read_beats==7&&write_beats==4,"response beat accounting");
  check(req_ready&&!done,"DMA not idle or completion duplicated");
  $display("PASS DMA_EDGE_REVIEW cycles=%0d jobs=%0d errors=%0d read_beats=%0d write_beats=%0d",cycles,done_count,error_count,read_beats,write_beats);
  $finish;
 end
endmodule
