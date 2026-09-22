// Additional review tests, reusing only the original AXI memory/clock BFM.
// Does not edit or replace the frozen RTL or its original test.
#define main original_wrapper_test_main
#include "../../rtl/sparse_gate_axi/tests/test_axi.cpp"
#undef main

static unsigned raw_write(Bench& b,unsigned off,unsigned size,uint32_t strobe,
                          std::array<uint32_t,8> data,unsigned len=0,bool last=true){
 b.d.s_axi_awaddr=0x900f0000+off;b.d.s_axi_awid=0x55;
 b.d.s_axi_awlen=len;b.d.s_axi_awsize=size;b.d.s_axi_awburst=1;
 for(int i=0;i<8;i++)b.d.s_axi_wdata[i]=data[i];
 b.d.s_axi_wstrb=strobe;b.d.s_axi_wlast=last;
 bool a=false,w=false;
 while(!a||!w){b.d.s_axi_awvalid=!a;b.d.s_axi_wvalid=!w;b.step();a|=b.haw;w|=b.hw;}
 b.d.s_axi_awvalid=0;b.d.s_axi_wvalid=0;
 if(!last){
  for(int i=0;i<7;i++){b.step();b.check(!b.d.s_axi_bvalid,"B issued before draining burst WLAST");}
  b.d.s_axi_wlast=1;b.d.s_axi_wvalid=1;do{b.step();}while(!b.hw);b.d.s_axi_wvalid=0;
 }
 for(int i=0;i<5;i++)b.step();
 b.d.s_axi_bready=1;do{b.step();}while(!b.hb);b.d.s_axi_bready=0;
 return b.hresp;
}

static void configure(Bench& b,unsigned n,unsigned k){
 for(auto item:std::vector<std::pair<unsigned,unsigned>>{
  {0x10,0x90001000},{0x14,0},{0x18,0x90020000},{0x1c,0},
  {0x20,0x90010000},{0x24,0},{0x28,0x90060000},{0x2c,0},
  {0x30,0},{0x34,0},{0x38,0},{0x3c,0},{0x40,n},{0x44,1},
  {0x48,k},{0x4c,1},{0x50,41},{0x54,7},{0x58,0}})b.reg(item.first,item.second);
 b.mem[0x1000+68]=0x80;b.mem[0x1000+69]=0x3f;
 for(int i=64;i<68;i++)b.mem[0x1000+i]=127;
 for(unsigned j=0;j<n;j++)for(int i=64;i<68;i++)b.mem[0x20000+j*96+i]=127;
}

int main(){try{
 Bench b;std::array<uint32_t,8> data{};
 // Byte writes must preserve every non-strobed byte and respect addressed lane.
 b.reg(0x50,0x11223344);data[4]=0x0000aa00;
 b.check(raw_write(b,0x51,0,1u<<17,data)==0,"legal byte write rejected");
 b.check(b.rr(0x50)==0x1122aa44,"byte lane/WSTRB changed wrong bytes");
 data[4]=0x00000077;
 b.check(raw_write(b,0x51,0,1u<<16,data)==2,"outside AWSIZE strobe accepted");
 b.check(b.rr(0x50)==0x1122aa44,"invalid byte strobe modified cfg");
 // All lanes in an ordinary writable register line are real 32B writes.
 for(unsigned i=0;i<8;i++)data[i]=0x98765000+i;
 b.check(raw_write(b,0x20,5,0xffffffff,data)==0,"32B write rejected");
 for(unsigned i=0;i<8;i++)b.check(b.rr(0x20+i*4)==data[i],"32B lane readback");
 // A legal two-beat AXI transaction is unsupported MMIO: drain and SLVERR.
 data.fill(0);data[3]=1;
 b.check(raw_write(b,0xc,2,0xf000,data,1,false)==2,"bad burst response");
 b.reg(0xc,0);b.check(b.rr(0xc)==0,"write channel failed after bad burst");
 // Unsupported read burst must return the requested count with stable error.
 b.d.s_axi_araddr=0x900f0050;b.d.s_axi_arid=0x88;b.d.s_axi_arlen=2;
 b.d.s_axi_arsize=2;b.d.s_axi_arburst=1;b.d.s_axi_arvalid=1;
 do{b.step();}while(!b.har);b.d.s_axi_arvalid=0;
 for(int i=0;i<3;i++){
  for(int j=0;j<4;j++)b.step();
  b.check(b.d.s_axi_rvalid&&b.d.s_axi_rresp==2&&b.d.s_axi_rid==0x88,"read burst response");
  b.check(bool(b.d.s_axi_rlast)==(i==2),"read burst RLAST");
  b.d.s_axi_rready=1;do{b.step();}while(!b.hr);b.d.s_axi_rready=0;
 }
 b.check(b.rr(0)==0x53474154,"read recovery");
 std::cout<<"CHECK narrow32_wstrb_and_burst_drain PASS\n";
 // Exercise wrapper insertion/cache/output indices at physical entry511.
 configure(b,520,512);
 b.reg(0xc,0);b.reg(8,1);
 b.check(b.wr(0x54,999)==2,"busy config write was accepted");
 b.check(b.rr(0x54)==7,"busy config write changed epoch");
 unsigned status;do{status=b.rr(4);}while(status&1);
 b.check(status==2&&b.rr(0x5c)==512,"K512 completion/count");
 for(unsigned i=0;i<512;i++){
  b.check(b.u32(0x60000+i*32)==i,"K512 stable tie/output bound");
  b.check(b.u32(0x60000+i*32+4)==0,"K512 score bound");
 }
 b.check(b.rr(0x68)==3+520*3&&b.rr(0x6c)==512,"K512 DMA accounting");
 b.check(b.run(2)==2&&b.rr(0x68)==0&&b.rr(0x6c)==512,"K512 reuse");
 std::cout<<"CHECK full_wrapper_K512_and_busy_write PASS\n";
 // A write response held after data delivery cannot expose DONE/cache commit.
 configure(b,1,1);b.reg(0xc,0);b.reg(8,1);
 do{b.step();}while(!b.b);
 b.bdue=b.t+10000;
 for(int i=0;i<50;i++)b.step();
 b.check((b.rr(4)&7)==1&&b.rr(0x74)==0,"false DONE before output BRESP");
 b.bdue=b.t;do{status=b.rr(4);}while(status&1);
 b.check(status==2&&b.rr(0x74)==1,"no DONE after final BRESP");
 std::cout<<"CHECK final_BRESP_commit_gate PASS\n";
 // Independently vary all seven documented selection-cache identity fields.
 for(auto key:std::vector<std::pair<unsigned,unsigned>>{{0x50,42},{0x54,8},{0x40,2},
     {0x48,2},{0x4c,2},{0x10,0x90001060},{0x18,0x90020060}}){
  configure(b,1,1);b.check(b.run(0)==2,"cache identity setup");
  b.reg(key.first,key.second);b.check((b.run(2)&0xff07)==0x204,"cache identity key omitted");
 }
 std::cout<<"CHECK all_seven_reuse_identity_fields PASS\n";
 // Physical REINDEX must not inspect an unlisted, even malformed, K record.
 configure(b,8,1);b.mem[0x20000+6*96+64]=255;
 unsigned id0=0;std::memcpy(&b.mem[0x10000],&id0,4);
 b.check(b.run(1)==2&&b.rr(0x68)==7&&b.rr(0x70)==1,"unlisted K observed by REINDEX");
 b.mem[0x20000+6*96+64]=127;
 std::cout<<"CHECK physically_unlisted_K_not_observed PASS\n";
 configure(b,1,1);b.check(b.run(0)==2,"illegal command setup");
 // An illegal command currently leaves the previously committed cache valid.
 b.check(b.wr(8,3)==2,"illegal command not rejected");
 b.check((b.rr(4)&0xff07)==0x604,"illegal command status");
 unsigned cache_after_illegal=b.rr(0x74),reuse_after_illegal=b.run(2);
 std::cout<<"OBSERVE illegal_command_cache_valid="<<cache_after_illegal
          <<" subsequent_reuse_status="<<reuse_after_illegal<<"\n";
 b.check(cache_after_illegal==1&&reuse_after_illegal==2,"observation changed; revisit review");
 std::cout<<"PASS EXTRA_WRAPPER_EDGE_REVIEW cycles="<<b.t<<"\n";
 return 0;
}catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<"\n";return 1;}}
