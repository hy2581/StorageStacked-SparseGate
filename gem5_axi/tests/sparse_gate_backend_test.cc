#include "sparse_gate_backend.hh"
#include <filesystem>
#include <iostream>
#include <stdexcept>
using namespace sc_core;
static void check(bool b,const char* why){if(!b)throw std::runtime_error(why);}
int sc_main(int argc,char**argv){
    check(argc==3,"library and output directory required");
    sc_set_time_resolution(1,SC_FS);std::filesystem::create_directories(argv[2]);
    sc_clock clock("clock",sc_time(2,SC_NS));sc_signal<bool> resetn;
    sc_fifo<SimpleMemRequest> hreq(8),mreq(8);sc_fifo<SimpleMemResponse> hrsp(8),mrsp(8);
    storage_axi::SparseGateBackend gate("gate",argv[1],0x900f0000,argv[2]);
    gate.clk(clock);gate.resetn(resetn);gate.host_request(hreq);gate.host_response(hrsp);gate.memory_request(mreq);gate.memory_response(mrsp);
    resetn=false;sc_start(12,SC_NS);resetn=true;sc_start(4,SC_NS);
    unsigned ident=1,cases=0;
    auto transaction=[&](bool write,unsigned offset,unsigned lock,unsigned beats,uint32_t value){
        SimpleMemRequest r;r.write=write;r.rp=2;r.address.addr=0x900f0000+offset;
        r.address.id=ident++;r.address.user=77;r.address.size=2;r.address.len=beats-1;r.address.burst=1;r.address.lock=lock;
        if(write){r.write_beats.resize(beats);for(unsigned b=0;b<beats;++b){unsigned lane=(offset+4*b)%32;
            for(unsigned j=0;j<4;++j){r.write_beats[b].data[lane+j]=value>>(8*j);r.write_beats[b].strobe[lane+j]=1;}}}
        check(hreq.nb_write(r),"host request queue full");SimpleMemResponse s;bool got=false;
        for(unsigned i=0;i<100&&!got;++i){sc_start(2,SC_NS);got=hrsp.nb_read(s);check(!mreq.num_available(),"MMIO unexpectedly sent memory request");}
        check(got&&s.write==write&&s.id==r.address.id&&s.rp==r.rp&&s.user==77,"response identity or timeout");
        check(s.resp==(lock?2:0),"wrong response status");check(s.read_beats.size()==(write?0:beats),"wrong response shape");
        for(const auto& b:s.read_beats)check(b.resp==(lock?2:0)&&b.user==77,"read status/user changed");
        ++cases;return s;
    };
    transaction(true,0x0c,1,1,2); // locked MODE must not alter reset FULL mode
    auto mode=transaction(false,0x0c,0,1,0);for(unsigned j=12;j<16;++j)check(mode.read_beats[0].data[j]==0,"exclusive write changed MODE");
    transaction(false,0,1,1,0);transaction(false,0,1,4,0);transaction(true,8,1,1,1); // no START/DMA
    auto id=transaction(false,0,0,1,0);uint32_t v=0;for(unsigned j=0;j<4;++j)v|=uint32_t(id.read_beats[0].data[j])<<(8*j);
    check(v==0x53474154,"ID read did not recover after rejects");
    auto status=transaction(false,4,0,1,0);for(unsigned j=4;j<8;++j)check(status.read_beats[0].data[j]==0,"locked START changed state");
    sc_start(8,SC_NS);gate.finish();
    std::cout<<"BACKEND CONTRACT PASS cases="<<cases<<" exclusive_rejections=4 memory_requests=0\n";return 0;
}
