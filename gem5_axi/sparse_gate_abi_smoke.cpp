// Tests the shared-object boundary itself, using the real generated RTL.
#include "sparse_gate_abi.h"
#include <cstdint>
#include <cstdio>
#include <stdexcept>
static void check(bool ok,const char *msg){if(!ok)throw std::runtime_error(msg);}
struct Driver {
    void *p=sparse_gate_create();SparseGateInputs in{};SparseGateOutputs out{};uint64_t t=0;
    ~Driver(){sparse_gate_destroy(p);}
    void eval(unsigned clk){in.clk=clk;t+=1000000;check(!sparse_gate_eval(p,&in,&out,t),sparse_gate_last_error(p));}
    SparseGateOutputs tick(){eval(0);auto before=out;eval(1);return before;}
    uint32_t read(uint64_t a,unsigned len=0){
        in.s_axi_araddr=a;in.s_axi_arid=0xa35;in.s_axi_arlen=len;in.s_axi_arsize=2;
        in.s_axi_arburst=1;in.s_axi_arvalid=1;bool sent=false;
        for(unsigned n=0;n<100;++n)if(tick().s_axi_arready){sent=true;break;}
        check(sent,"AR timeout");in.s_axi_arvalid=0;in.s_axi_rready=0;
        SparseGateOutputs held{};bool valid=false;
        for(unsigned n=0;n<100;++n){auto o=tick();if(o.s_axi_rvalid){held=o;valid=true;break;}}
        check(valid,"R timeout");auto o=tick();check(o.s_axi_rvalid&&o.s_axi_rid==held.s_axi_rid&&o.s_axi_rdata[(a&31)/4]==held.s_axi_rdata[(a&31)/4],"R changed while blocked");
        in.s_axi_rready=1;unsigned beats=0;uint32_t value=0;
        for(unsigned n=0;n<100;++n){o=tick();if(!o.s_axi_rvalid)continue;
            check(o.s_axi_rid==0xa35&&o.s_axi_rresp==(len?2:0),"R id/response");
            if(!beats)value=o.s_axi_rdata[(a&31)/4];++beats;
            check(bool(o.s_axi_rlast)==(beats==len+1),"R length");if(o.s_axi_rlast)break;}
        check(beats==len+1,"R drain timeout");in.s_axi_rready=0;return value;
    }
    void write(uint64_t a,uint32_t value,unsigned strobe,bool wfirst){
        in.s_axi_awaddr=a;in.s_axi_awid=0x713;in.s_axi_awlen=0;in.s_axi_awsize=2;in.s_axi_awburst=1;
        in.s_axi_wdata[(a&31)/4]=value;in.s_axi_wstrb=strobe;in.s_axi_wlast=1;
        bool aw=false,w=false;unsigned count=0;
        for(;count<100&&!(aw&&w);++count){
            in.s_axi_awvalid=!aw&&(!wfirst||count>=3);in.s_axi_wvalid=!w&&(wfirst||count>=3);
            auto o=tick();aw|=in.s_axi_awvalid&&o.s_axi_awready;w|=in.s_axi_wvalid&&o.s_axi_wready;}
        check(aw&&w,"AW/W timeout");in.s_axi_awvalid=in.s_axi_wvalid=0;
        in.s_axi_bready=0;SparseGateOutputs held{};bool valid=false;
        for(unsigned n=0;n<100;++n){auto o=tick();if(o.s_axi_bvalid){held=o;valid=true;break;}}
        check(valid,"B timeout");auto o=tick();check(o.s_axi_bvalid&&o.s_axi_bid==held.s_axi_bid&&o.s_axi_bresp==held.s_axi_bresp,"B changed while blocked");
        in.s_axi_bready=1;o=tick();check(o.s_axi_bvalid&&o.s_axi_bid==0x713&&o.s_axi_bresp==0,"B id/response");in.s_axi_bready=0;
    }
};
int main(int argc,char **argv){try{
    check(sparse_gate_abi_version()==SPARSE_GATE_ABI_VERSION&&sparse_gate_input_size()==sizeof(SparseGateInputs)&&sparse_gate_output_size()==sizeof(SparseGateOutputs),"ABI mismatch");
    Driver d;check(d.p,"create failed");if(argc>1)check(!sparse_gate_trace_open(d.p,argv[1]),"trace open failed");
    for(int i=0;i<5;++i)d.tick();d.in.rst_n=1;d.tick();
    check(d.read(0x900f0000)==0x53474154,"ID read");
    d.write(0x900f0010,0x11223344,0xf0000,false);check(d.read(0x900f0010)==0x11223344,"AW-first lane mapping");
    d.write(0x900f0010,0x00000099,0x10000,true);check(d.read(0x900f0010)==0x11223399,"W-first byte mask");
    d.read(0x900f0000,3);check(d.read(0x900f0000)==0x53474154,"recovery after bad burst");
    std::printf("SPARSE_GATE_ABI_SMOKE_PASS build_id=%s time_fs=%llu\n",sparse_gate_build_id(),(unsigned long long)d.t);
    return 0;
}catch(const std::exception& e){std::fprintf(stderr,"ABI smoke failed: %s\n",e.what());return 1;}}
