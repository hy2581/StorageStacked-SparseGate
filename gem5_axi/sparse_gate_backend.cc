#include "sparse_gate_backend.hh"
#include "sparse_gate_abi.h"
#include "axi_contract.h"
#include "sim/cur_tick.hh"
#include <dlfcn.h>
#include <deque>
#include <fstream>
#include <iomanip>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <utility>
#include <tuple>

namespace storage_axi {
namespace {
constexpr size_t QueueLimit=8, TagLimit=32;
void require(bool ok, const char *why) {
    if (!ok) throw std::runtime_error(std::string("SparseGate adapter: ")+why);
}
template<class T> T symbol(void *lib,const char *name) {
    dlerror(); auto p=dlsym(lib,name); const auto *e=dlerror();
    if(e) throw std::runtime_error(std::string("SparseGate ABI missing ")+name+": "+e);
    return reinterpret_cast<T>(p);
}
void to_words(const std::array<uint8_t,32>& bytes,uint32_t *words) {
    for(unsigned i=0;i<8;++i) {
        words[i]=0; for(unsigned b=0;b<4;++b) words[i]|=uint32_t(bytes[4*i+b])<<(8*b);
    }
}
void from_words(const uint32_t *words,std::array<uint8_t,32>& bytes) {
    for(unsigned i=0;i<32;++i) bytes[i]=uint8_t(words[i/4]>>(8*(i%4)));
}
}
struct SparseGateBackend::State {
    SparseGateBackend& owner;
    void *library=nullptr, *model=nullptr;
    decltype(&sparse_gate_eval) evaluate=nullptr;
    decltype(&sparse_gate_last_error) error=nullptr;
    decltype(&sparse_gate_destroy) destroy=nullptr;
    decltype(&sparse_gate_trace_flush) flush_trace=nullptr;
    std::string build_id, dir;
    uint64_t base;
    SparseGateInputs in{};
    SparseGateOutputs out{};
    struct Mmio {
        SimpleMemRequest req;
        SimpleMemResponse rsp;
        bool address_sent=false, complete=false;
        unsigned writes_sent=0;
    };
    struct Ticket { bool dma; bool write; uint8_t rp; uint16_t id,user; uint64_t addr; unsigned beats; };
    std::map<uint16_t,Ticket> tickets;
    uint16_t next_tag=1;
    std::deque<SimpleMemRequest> pending, bypass, mmio_wait;
    std::deque<SimpleMemResponse> completed;
    // AouTarget matches the oldest ticket of each (direction, plane, wire ID).
    // Serialize admission within that group even if an external producer later
    // permits ID reuse before completion; MMIO must not pass an older RAM burst.
    std::set<std::tuple<bool,uint8_t,uint16_t>> active_host_groups;
    std::optional<Mmio> mmio;
    std::optional<AxChannel> dma_aw;
    std::optional<SimpleMemWriteBeat> dma_w;
    std::optional<SimpleMemRequest> dma_request;
    std::optional<SimpleMemResponse> dma_response;
    bool dma_active=false, prefer_dma=true, ever_started=false;
    uint64_t cycles=0, mmio_reads=0, mmio_writes=0, bypass_count=0,
             dma_reads=0,dma_writes=0, memory_issued=0,memory_completed=0,
             host_completed=0, dma_read_completed=0,dma_write_completed=0, mmio_rejected=0;
    std::ofstream events;
    State(SparseGateBackend& o,const std::string& path,uint64_t b,const std::string& d)
      : owner(o),dir(d),base(b),events(d+"/sparse_gate_events.csv") {
        require(!(base&4095),"MMIO base must be page aligned");
        require(bool(events),"cannot open event log");
        events<<"tick_fs,cycle,event,source,tag,id,write,address,beats,resp,data_hex,strb_hex\n";
        library=dlopen(path.c_str(),RTLD_NOW|RTLD_LOCAL);
        if(!library) throw std::runtime_error(std::string("cannot load SparseGate RTL model: ")+dlerror());
        try {
            require(symbol<decltype(&sparse_gate_abi_version)>(library,"sparse_gate_abi_version")()==SPARSE_GATE_ABI_VERSION,"ABI version mismatch");
            require(symbol<decltype(&sparse_gate_input_size)>(library,"sparse_gate_input_size")()==sizeof(in),"ABI input size mismatch");
            require(symbol<decltype(&sparse_gate_output_size)>(library,"sparse_gate_output_size")()==sizeof(out),"ABI output size mismatch");
            build_id=symbol<decltype(&sparse_gate_build_id)>(library,"sparse_gate_build_id")();
            evaluate=symbol<decltype(evaluate)>(library,"sparse_gate_eval");
            error=symbol<decltype(error)>(library,"sparse_gate_last_error");
            destroy=symbol<decltype(destroy)>(library,"sparse_gate_destroy");
            flush_trace=symbol<decltype(flush_trace)>(library,"sparse_gate_trace_flush");
            model=symbol<decltype(&sparse_gate_create)>(library,"sparse_gate_create")();
            require(model!=nullptr,"model construction failed");
            require(symbol<decltype(&sparse_gate_trace_open)>(library,"sparse_gate_trace_open")(model,(d+"/sparse_gate.vcd").c_str())==0,"RTL trace open failed");
        } catch(...) { if(model&&destroy)destroy(model);dlclose(library);throw; }
    }
    ~State() { if(model&&destroy)destroy(model);if(library)dlclose(library); }
    void eval() {
        if(evaluate(model,&in,&out,gem5::curTick()))
            throw std::runtime_error(std::string("SparseGate RTL eval failed: ")+error(model));
    }
    void log(const char *event,const char *source,unsigned tag,unsigned id,bool write,
             uint64_t addr,unsigned beats,unsigned resp=0,const uint32_t *data=nullptr,uint32_t strb=0) {
        events<<gem5::curTick()<<','<<cycles<<','<<event<<','<<source<<','<<tag<<','<<id<<','<<write<<','<<addr<<','<<beats<<','<<resp<<',';
        if(data)for(int i=7;i>=0;--i)events<<std::hex<<std::setw(8)<<std::setfill('0')<<data[i];
        events<<','<<std::hex<<strb<<std::dec<<'\n';
    }
    bool is_mmio(uint64_t addr)const { return addr>=base && addr-base<4096; }
    uint16_t tag() {
        require(tickets.size()<TagLimit,"too many internal tags");
        for(unsigned i=0;i<1023;++i) {
            unsigned value=next_tag++;if(next_tag>1023)next_tag=1;
            if(!tickets.count(value))return value;
        }
        throw std::runtime_error("no SparseGate memory tag");
    }
    void queue_host() {
        SimpleMemRequest req;
        if(pending.size()<QueueLimit && owner.host_request.nb_read(req)) {
            require(!axi_request_error(req.address),"invalid host request geometry");
            require(!req.write || req.write_beats.size()==req.beats(),"invalid host write beat count");
            pending.push_back(std::move(req));
        }
        if(!pending.empty()) {
            const auto group=std::make_tuple(pending.front().write,pending.front().rp,pending.front().address.id);
            auto& queue=is_mmio(pending.front().address.addr)?mmio_wait:bypass;
            if(queue.size()<QueueLimit&&!active_host_groups.count(group)) {
                active_host_groups.insert(group);queue.push_back(std::move(pending.front()));pending.pop_front();
            }
        }
        if(!mmio && !mmio_wait.empty()) {
            // This slave has no exclusive monitor. Preserve the original
            // MemSimBackend SLVERR contract without issuing any RTL transaction.
            // The complete parent write has already been collected by AouTarget.
            if(mmio_wait.front().address.lock) {
                if(completed.size()>=QueueLimit)return;
                const auto& r=mmio_wait.front();SimpleMemResponse rsp;
                rsp.write=r.write;rsp.rp=r.rp;rsp.id=r.address.id;rsp.user=r.address.user;rsp.resp=2;
                if(!r.write) {
                    rsp.read_beats.resize(r.beats());
                    for(auto& beat:rsp.read_beats){beat.resp=2;beat.user=r.address.user;}
                }
                if(r.write)++mmio_writes;else ++mmio_reads;
                log("mmio_reject","HOST",0,r.address.id,r.write,r.address.addr,r.beats(),2);
                ++mmio_rejected;completed.push_back(std::move(rsp));mmio_wait.pop_front();return;
            }
            Mmio m; m.req=std::move(mmio_wait.front());mmio_wait.pop_front();
            m.rsp.write=m.req.write;m.rsp.rp=m.req.rp;m.rsp.id=m.req.address.id;m.rsp.user=m.req.address.user;
            if(m.req.write)++mmio_writes;else ++mmio_reads;
            log("mmio_begin","HOST",0,m.req.address.id,m.req.write,m.req.address.addr,m.req.beats());
            mmio=std::move(m);
        }
    }
    void memory_return() {
        // A full response queue propagates backpressure into the shared backend.
        if(completed.size()>=QueueLimit || dma_response) return;
        SimpleMemResponse rsp;
        if(!owner.memory_response.nb_read(rsp))return;
        auto it=tickets.find(rsp.id);require(it!=tickets.end(),"unknown memory response tag");
        const auto t=it->second;
        require(rsp.write==t.write,"memory response direction changed");
        require(rsp.rp==t.rp,"memory response resource plane changed");
        require(t.write || rsp.read_beats.size()==t.beats,"memory read response length changed");
        log("memory_return",t.dma?"DMA":"HOST",rsp.id,t.id,rsp.write,t.addr,t.beats,rsp.resp);
        rsp.id=t.id;rsp.rp=t.rp;rsp.user=t.user;
        if(t.dma) { require(dma_active,"DMA returned while idle");dma_response=std::move(rsp); }
        else completed.push_back(std::move(rsp));
        tickets.erase(it);++memory_completed;
    }
    void memory_issue() {
        if(tickets.size()>=TagLimit)return;
        bool use_dma=bool(dma_request)&&(prefer_dma||bypass.empty());
        if(!use_dma && bypass.empty())return;
        const auto& original=use_dma?*dma_request:bypass.front();
        auto req=original; const auto id=tag();req.address.id=id;
        if(!owner.memory_request.nb_write(req))return;
        tickets.emplace(id,Ticket{use_dma,req.write,req.rp,original.address.id,req.address.user,req.address.addr,req.beats()});
        log("memory_issue",use_dma?"DMA":"HOST",id,original.address.id,req.write,req.address.addr,req.beats());
        ++memory_issued;prefer_dma=!use_dma;
        if(use_dma)dma_request.reset();else { bypass.pop_front();++bypass_count; }
    }
    void slave_handshakes(const SparseGateOutputs& p) {
        if(!mmio)return;
        auto& m=*mmio;const auto& a=m.req.address;
        if(in.s_axi_awvalid&&p.s_axi_awready) {
            require(m.req.write&&!m.address_sent,"duplicate MMIO AW");m.address_sent=true;
            log("S_AW","HOST",0,a.id,true,a.addr,m.req.beats());
        }
        if(in.s_axi_wvalid&&p.s_axi_wready) {
            ++m.writes_sent;log("S_W","HOST",0,a.id,true,a.addr,m.req.beats(),0,in.s_axi_wdata,in.s_axi_wstrb);
        }
        if(in.s_axi_arvalid&&p.s_axi_arready) {
            require(!m.req.write&&!m.address_sent,"duplicate MMIO AR");m.address_sent=true;
            log("S_AR","HOST",0,a.id,false,a.addr,m.req.beats());
        }
        if(p.s_axi_bvalid&&in.s_axi_bready) {
            require(m.req.write&&m.address_sent&&m.writes_sent==m.req.beats(),"premature MMIO B");
            require(p.s_axi_bid==a.id,"MMIO BID mismatch");
            m.rsp.resp=p.s_axi_bresp;m.complete=true;
            log("S_B","HOST",0,p.s_axi_bid,true,a.addr,m.req.beats(),p.s_axi_bresp);
        }
        if(p.s_axi_rvalid&&in.s_axi_rready) {
            require(!m.req.write&&m.address_sent,"premature MMIO R");
            require(p.s_axi_rid==a.id,"MMIO RID mismatch");
            require(bool(p.s_axi_rlast)==(m.rsp.read_beats.size()+1==m.req.beats()),"MMIO RLAST mismatch");
            SimpleMemReadBeat b;b.resp=p.s_axi_rresp;b.user=a.user;from_words(p.s_axi_rdata,b.data);
            m.rsp.read_beats.push_back(b);if(p.s_axi_rlast)m.complete=true;
            log("S_R","HOST",0,p.s_axi_rid,false,a.addr,m.req.beats(),p.s_axi_rresp,p.s_axi_rdata);
        }
        if(m.complete&&completed.size()<QueueLimit) { completed.push_back(std::move(m.rsp));mmio.reset(); }
    }
    AxChannel dma_address(bool write,const SparseGateOutputs& p) {
        AxChannel a;
        a.id=write?p.m_axi_awid:p.m_axi_arid;a.addr=write?p.m_axi_awaddr:p.m_axi_araddr;
        a.len=write?p.m_axi_awlen:p.m_axi_arlen;a.size=write?p.m_axi_awsize:p.m_axi_arsize;
        a.burst=write?p.m_axi_awburst:p.m_axi_arburst;
        require(a.id==1&&a.len==0&&a.size==5&&a.burst==1&&!(a.addr&31),"RTL DMA violates single-beat AXI256 contract");
        require(!is_mmio(a.addr),"recursive DMA to MMIO aperture");
        return a;
    }
    void master_handshakes(const SparseGateOutputs& p) {
        if(p.m_axi_awvalid&&in.m_axi_awready) {
            require(!dma_active&&!dma_aw,"duplicate/outstanding DMA AW");dma_aw=dma_address(true,p);
            log("M_AW","DMA",0,p.m_axi_awid,true,p.m_axi_awaddr,1);
        }
        if(p.m_axi_wvalid&&in.m_axi_wready) {
            require(!dma_active&&!dma_w&&p.m_axi_wlast,"duplicate/outstanding DMA W or missing WLAST");
            SimpleMemWriteBeat b;from_words(p.m_axi_wdata,b.data);
            for(unsigned i=0;i<32;++i)b.strobe[i]=(p.m_axi_wstrb>>i)&1;
            dma_w=b;log("M_W","DMA",0,1,true,dma_aw?dma_aw->addr:0,1,0,p.m_axi_wdata,p.m_axi_wstrb);
        }
        if(p.m_axi_arvalid&&in.m_axi_arready) {
            require(!dma_active&&!dma_aw&&!dma_w,"DMA read/write overlap");
            SimpleMemRequest r;r.address=dma_address(false,p);dma_request=r;dma_active=true;++dma_reads;
            log("M_AR","DMA",0,p.m_axi_arid,false,p.m_axi_araddr,1);
        }
        if(dma_aw&&dma_w) {
            require(!dma_active&&!dma_request,"duplicate DMA transaction");
            SimpleMemRequest r;r.write=true;r.address=*dma_aw;r.write_beats.push_back(*dma_w);
            dma_request=std::move(r);dma_active=true;dma_aw.reset();dma_w.reset();++dma_writes;
        }
        if(in.m_axi_bvalid&&p.m_axi_bready) {
            require(dma_response&&dma_response->write,"DMA B without matching return");
            log("M_B","DMA",0,in.m_axi_bid,true,0,1,in.m_axi_bresp);
            dma_response.reset();dma_active=false;++dma_write_completed;
        }
        if(in.m_axi_rvalid&&p.m_axi_rready) {
            require(dma_response&&!dma_response->write,"DMA R without matching return");
            log("M_R","DMA",0,in.m_axi_rid,false,0,1,in.m_axi_rresp,in.m_axi_rdata);
            dma_response.reset();dma_active=false;++dma_read_completed;
        }
    }
    void prepare() {
        in={};in.rst_n=owner.resetn.read();in.clk=0;
        if(!in.rst_n)return;
        if(mmio&&!mmio->complete) {
            const auto& m=*mmio;const auto& a=m.req.address;
            if(m.req.write) {
                in.s_axi_awvalid=!m.address_sent;in.s_axi_awaddr=a.addr;in.s_axi_awid=a.id;
                in.s_axi_awlen=a.len;in.s_axi_awsize=a.size;in.s_axi_awburst=a.burst;
                in.s_axi_wvalid=m.writes_sent<m.req.beats();
                if(in.s_axi_wvalid) {
                    const auto& w=m.req.write_beats[m.writes_sent];to_words(w.data,in.s_axi_wdata);
                    for(unsigned i=0;i<32;++i)if(w.strobe[i])in.s_axi_wstrb|=uint32_t(1)<<i;
                    in.s_axi_wlast=m.writes_sent+1==m.req.beats();
                }
                in.s_axi_bready=m.address_sent&&m.writes_sent==m.req.beats()&&completed.size()<QueueLimit;
            } else {
                in.s_axi_arvalid=!m.address_sent;in.s_axi_araddr=a.addr;in.s_axi_arid=a.id;
                in.s_axi_arlen=a.len;in.s_axi_arsize=a.size;in.s_axi_arburst=a.burst;
                in.s_axi_rready=m.address_sent&&m.rsp.read_beats.size()<m.req.beats()&&completed.size()<QueueLimit;
            }
        }
        in.m_axi_awready=!dma_active&&!dma_aw;
        in.m_axi_wready=!dma_active&&!dma_w;
        in.m_axi_arready=!dma_active&&!dma_aw&&!dma_w;
        if(dma_response) {
            const auto& r=*dma_response;
            if(r.write) { in.m_axi_bvalid=1;in.m_axi_bid=r.id;in.m_axi_bresp=r.resp; }
            else {
                require(r.read_beats.size()==1,"DMA return length changed");
                in.m_axi_rvalid=1;in.m_axi_rid=r.id;in.m_axi_rresp=r.read_beats[0].resp;in.m_axi_rlast=1;
                to_words(r.read_beats[0].data,in.m_axi_rdata);
            }
        }
    }
    void edge() {
        require(sc_core::sc_time_stamp().value()==gem5::curTick(),"split simulation clocks");
        if(!owner.clk.read()) { prepare();eval();return; }
        // Inputs and combinational outputs were settled on the preceding falling
        // edge. Capture exactly those handshakes, then advance the real RTL once.
        const auto before=out;in.clk=1;in.rst_n=owner.resetn.read();eval();
        if(!in.rst_n) { require(!ever_started,"in-flight reset recovery is unsupported");return; }
        ever_started=true;++cycles;
        slave_handshakes(before);master_handshakes(before);
        if(!completed.empty()&&owner.host_response.nb_write(completed.front())) {
            const auto& r=completed.front();
            require(active_host_groups.erase(std::make_tuple(r.write,r.rp,r.id))==1,"host response has no admitted group");
            completed.pop_front();++host_completed;
        }
        memory_return();queue_host();memory_issue();
    }
    void finish() {
        events.flush();
        flush_trace(model);
        require(pending.empty()&&bypass.empty()&&mmio_wait.empty()&&completed.empty()&&!mmio&&active_host_groups.empty(),
                "unfinished host transactions");
        require(tickets.empty()&&!dma_active&&!dma_aw&&!dma_w&&!dma_request&&!dma_response,
                "unfinished RTL DMA transactions");
        require(owner.host_request.num_available()==0&&owner.memory_response.num_available()==0,"undrained input FIFOs");
        require(memory_issued==memory_completed,"memory request/return count mismatch");
        require(host_completed==bypass_count+mmio_reads+mmio_writes,"host request/return count mismatch");
        require(dma_reads==dma_read_completed&&dma_writes==dma_write_completed,"DMA request/return count mismatch");
        std::ofstream f(dir+"/sparse_gate_summary.json");
        f<<"{\"schema\":\"sparse_gate_adapter_v1\",\"drained\":true,\"build_id\":\""<<build_id
         <<"\",\"abi_version\":"<<SPARSE_GATE_ABI_VERSION<<",\"time_unit_fs\":1,\"cycles\":"<<cycles
         <<",\"mmio_reads\":"<<mmio_reads<<",\"mmio_writes\":"<<mmio_writes
         <<",\"mmio_rejected\":"<<mmio_rejected
         <<",\"host_bypass\":"<<bypass_count<<",\"host_completed\":"<<host_completed
         <<",\"dma_reads\":"<<dma_reads<<",\"dma_writes\":"<<dma_writes
         <<",\"dma_read_completed\":"<<dma_read_completed<<",\"dma_write_completed\":"<<dma_write_completed
         <<",\"memory_issued\":"<<memory_issued<<",\"memory_completed\":"<<memory_completed<<"}\n";
    }
};
SparseGateBackend::SparseGateBackend(sc_core::sc_module_name n,const std::string& library,
                                   uint64_t base,const std::string& dir)
 : sc_module(n),state(std::make_unique<State>(*this,library,base,dir)) {
    SC_METHOD(edge);sensitive<<clk;
}
SparseGateBackend::~SparseGateBackend()=default;
void SparseGateBackend::edge() { state->edge(); }
void SparseGateBackend::finish() { state->finish(); }
}
