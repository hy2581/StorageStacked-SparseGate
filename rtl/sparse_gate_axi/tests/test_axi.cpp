#include "Vsparse_gate_axi.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <string>
struct Bench {
 Vsparse_gate_axi d; std::vector<uint8_t> mem=std::vector<uint8_t>(1<<20,0);
 uint64_t t=0; uint32_t rng=918273;
 bool aw=false,w=false,r=false,b=false; uint64_t wa=0,ra=0;unsigned rdue=0,bdue=0;
 std::array<uint32_t,8> wd{},rd{};uint32_t ws=0;bool fail_read=false,fail_write=false;
 std::vector<uint64_t> stalled_aw,stalled_ar,stalled_w,stalled_b,stalled_r;
 void stability(std::vector<uint64_t>& prev,bool valid,bool ready,std::vector<uint64_t> now){
  if(!prev.empty())check(valid&&prev==now,"AXI stalled payload changed");
  prev=valid&&!ready?now:std::vector<uint64_t>{};
 }
 unsigned reads=0,writes=0;bool har=false,haw=false,hw=false,hr=false,hb=false;
 unsigned hresp=0;std::array<uint32_t,8> hdata{};
 uint32_t rand(){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return rng;}
 void check(bool ok,const char* s){if(!ok)throw std::runtime_error(std::string(s)+" cycle="+std::to_string(t));}
 void step(){
  d.clk=0;
  d.m_axi_awready=!aw&&(rand()%4!=0);d.m_axi_wready=!w&&(rand()%4!=0);
  d.m_axi_arready=!r&&(rand()%4!=0);
  d.m_axi_rvalid=r&&t>=rdue;d.m_axi_rid=1;d.m_axi_rresp=fail_read?2:0;d.m_axi_rlast=1;
  for(int i=0;i<8;i++)d.m_axi_rdata[i]=rd[i];
  d.m_axi_bvalid=b&&t>=bdue;d.m_axi_bid=1;d.m_axi_bresp=fail_write?2:0;
  d.eval();
  stability(stalled_aw,d.m_axi_awvalid,d.m_axi_awready,{d.m_axi_awaddr,d.m_axi_awid,d.m_axi_awlen,d.m_axi_awsize,d.m_axi_awburst});
  stability(stalled_ar,d.m_axi_arvalid,d.m_axi_arready,{d.m_axi_araddr,d.m_axi_arid,d.m_axi_arlen,d.m_axi_arsize,d.m_axi_arburst});
  stability(stalled_w,d.m_axi_wvalid,d.m_axi_wready,{d.m_axi_wdata[0],d.m_axi_wdata[1],d.m_axi_wdata[2],d.m_axi_wdata[3],d.m_axi_wdata[4],d.m_axi_wdata[5],d.m_axi_wdata[6],d.m_axi_wdata[7],d.m_axi_wstrb,d.m_axi_wlast});
  stability(stalled_b,d.s_axi_bvalid,d.s_axi_bready,{d.s_axi_bid,d.s_axi_bresp});
  stability(stalled_r,d.s_axi_rvalid,d.s_axi_rready,{d.s_axi_rdata[0],d.s_axi_rdata[1],d.s_axi_rdata[2],d.s_axi_rdata[3],d.s_axi_rdata[4],d.s_axi_rdata[5],d.s_axi_rdata[6],d.s_axi_rdata[7],d.s_axi_rid,d.s_axi_rresp,d.s_axi_rlast});
  haw=d.s_axi_awvalid&&d.s_axi_awready;hw=d.s_axi_wvalid&&d.s_axi_wready;
  har=d.s_axi_arvalid&&d.s_axi_arready;hr=d.s_axi_rvalid&&d.s_axi_rready;
  hb=d.s_axi_bvalid&&d.s_axi_bready;
  if(hr){hresp=d.s_axi_rresp;for(int i=0;i<8;i++)hdata[i]=d.s_axi_rdata[i];}
  if(hb)hresp=d.s_axi_bresp;
  bool ar_take=d.m_axi_arvalid&&d.m_axi_arready;
  bool aw_take=d.m_axi_awvalid&&d.m_axi_awready;
  bool w_take=d.m_axi_wvalid&&d.m_axi_wready;
  bool r_take=d.m_axi_rvalid&&d.m_axi_rready,b_take=d.m_axi_bvalid&&d.m_axi_bready;
  if(ar_take){
   check(d.m_axi_arid==1&&d.m_axi_arlen==0&&d.m_axi_arsize==5&&d.m_axi_arburst==1,"DMA AR shape");
   ra=d.m_axi_araddr;check(ra>=0x90000000&&ra+32<=0x90100000&&ra%32==0,"DMA AR bounds");
   std::memcpy(rd.data(),&mem[ra-0x90000000],32);r=true;rdue=t+2+rand()%15;reads++;
  }
  if(aw_take){check(d.m_axi_awid==1&&d.m_axi_awlen==0&&d.m_axi_awsize==5&&d.m_axi_awburst==1,"DMA AW shape");wa=d.m_axi_awaddr;aw=true;}
  if(w_take){for(int i=0;i<8;i++)wd[i]=d.m_axi_wdata[i];ws=d.m_axi_wstrb;check(d.m_axi_wlast,"WLAST");w=true;}
  if(r_take)r=false;
  if(b_take){b=false;aw=false;w=false;}
  if(aw&&w&&!b){
   check(wa>=0x90000000&&wa+32<=0x90100000&&wa%32==0,"DMA AW bounds");
   if(!fail_write)for(int i=0;i<32;i++)if(ws&(1u<<i))mem[wa-0x90000000+i]=reinterpret_cast<uint8_t*>(wd.data())[i];
   b=true;bdue=t+2+rand()%19;writes++;
  }
  d.clk=1;d.eval();t++;check(t<10000000,"global watchdog");
 }
 Bench(){d.rst_n=0;d.s_axi_bready=0;d.s_axi_rready=0;for(int i=0;i<5;i++)step();d.rst_n=1;step();}
 unsigned wr(unsigned off,uint32_t value,bool wfirst=false){
  d.s_axi_awaddr=0x900f0000+off;d.s_axi_awid=0x129;d.s_axi_awlen=0;d.s_axi_awsize=2;d.s_axi_awburst=1;
  for(int i=0;i<8;i++)d.s_axi_wdata[i]=0;
  d.s_axi_wdata[(off%32)/4]=value;d.s_axi_wstrb=15u<<(off%32);d.s_axi_wlast=1;
  bool a=false,wv=false;unsigned n=0;
  while(!a||!wv){
   d.s_axi_awvalid=!a&&(!wfirst||n>=3);d.s_axi_wvalid=!wv&&(wfirst||n>=4);step();
   a|=haw;wv|=hw;n++;check(n<10000,"MMIO write watchdog");
  }
  d.s_axi_awvalid=0;d.s_axi_wvalid=0;
  for(int i=0;i<3;i++)step(); // intentionally hold B
  d.s_axi_bready=1;do{step();}while(!hb);d.s_axi_bready=0;return hresp;
 }
 uint32_t rr(unsigned off){
  d.s_axi_araddr=0x900f0000+off;d.s_axi_arid=0x19b;d.s_axi_arlen=0;d.s_axi_arsize=2;d.s_axi_arburst=1;d.s_axi_arvalid=1;
  do{step();}while(!har);d.s_axi_arvalid=0;
  for(int i=0;i<4;i++)step(); // deliberately hold R
  d.s_axi_rready=1;do{step();}while(!hr);d.s_axi_rready=0;check(hresp==0,"MMIO read error");return hdata[(off%32)/4];
 }
 void reg(unsigned off,uint32_t value){check(wr(off,value,(off/4)%2)==0,"MMIO write error");}
 uint32_t run(unsigned mode){reg(0xc,mode);reg(8,1);unsigned s=0,n=0;do{s=rr(4);check(++n<200000,"job timeout");}while(s&1);std::cout<<"CASE mode="<<mode<<" status="<<s<<" cycles="<<rr(0x60)<<" reads="<<rr(0x68)<<" writes="<<rr(0x6c)<<" scores="<<rr(0x70)<<"\n";return s;}
 uint32_t u32(size_t off){uint32_t v;std::memcpy(&v,&mem.at(off),4);return v;}
};
static float nibble(unsigned n){float a[]={0,.5,1,1.5,2,3,4,6};return n&8?-a[n&7]:a[n&7];}
static uint32_t fbits(float f){uint32_t u;std::memcpy(&u,&f,4);return u;}
int main(){try{
 Bench b;constexpr unsigned QB=0x1000,KB=0x4000,CB=0x8000,OB=0x9000,VB=0x10000,GB=0x18000;
 constexpr unsigned H=4,N=25,K=5,VBYTES=288;
 b.check(b.rr(0)==0x53474154,"ID");
 for(unsigned h=0;h<H;h++){
  unsigned q=h%2?1:2;for(int j=0;j<64;j++)b.mem[QB+h*96+j]=q|(q<<4);
  for(int j=64;j<68;j++)b.mem[QB+h*96+j]=127;
  uint16_t weight=h==3?0xbf00:0x3f80;std::memcpy(&b.mem[QB+h*96+68],&weight,2);
 }
 std::vector<std::pair<float,unsigned>> all;
 for(unsigned k=0;k<N;k++){
  unsigned n=k%16;for(int j=0;j<64;j++)b.mem[KB+k*96+j]=n|(n<<4);
  for(int j=64;j<68;j++)b.mem[KB+k*96+j]=127;
  float sc=0;for(unsigned h=0;h<H;h++){
   float dot=128*nibble(h%2?1:2)*nibble(n);float weight=h==3?-.5f:1.f;sc+=std::max(0.f,dot)*weight;
  }all.push_back({sc,k});
  for(unsigned j=0;j<VBYTES;j++)b.mem[VB+k*VBYTES+j]=(k*37+j*13+9)&255;
 }
 for(auto item:std::vector<std::pair<unsigned,unsigned>>{{0x10,0x90000000+QB},{0x18,0x90000000+KB},
 {0x20,0x90000000+CB},{0x28,0x90000000+OB},{0x30,0x90000000+VB},{0x38,0x90000000+GB},
 {0x40,N},{0x44,4},{0x48,K},{0x4c,H},{0x50,41},{0x54,7},{0x58,VBYTES}})b.reg(item.first,item.second);
 auto verify=[&](std::vector<std::pair<float,unsigned>> values,unsigned count){
  std::sort(values.begin(),values.end(),[](auto a,auto c){return a.first!=c.first?a.first>c.first:a.second<c.second;});
  values.resize(std::min<size_t>(K,values.size()));std::sort(values.begin(),values.end(),[](auto a,auto c){return a.second<c.second;});
  b.check(b.rr(0x5c)==values.size(),"result count");
  for(size_t i=0;i<values.size();i++){
   b.check(b.u32(OB+i*32)==values[i].second,"selected index");b.check(b.u32(OB+i*32+4)==fbits(values[i].first),"selected score");
   for(unsigned j=0;j<VBYTES;j++)b.check(b.mem[GB+i*VBYTES+j]==b.mem[VB+values[i].second*VBYTES+j],"KV gathered byte");
  }b.check(b.rr(0x70)==count,"score count");return values.size();
 };
 b.check((b.run(2)&0xff04)==0x204,"reuse before commit rejected");
 b.reg(0x28,0x90000000+QB);b.check((b.run(0)&0xff04)==0x104,"output/input overlap rejected");b.reg(0x28,0x90000000+OB);
 b.reg(0x18,0xffffffe0);b.reg(0x1c,0xffffffff);b.check((b.run(0)&0xff04)==0x104,"address wrap rejected");b.reg(0x18,0x90000000+KB);b.reg(0x1c,0);
 b.check(b.run(0)==2,"FULL done");verify(all,N);
 b.check(b.rr(0x68)==H*3+N*3+K*(VBYTES/32),"FULL read accounting");
 b.check(b.rr(0x6c)==K*(1+VBYTES/32),"FULL write accounting");
 b.check(b.run(2)==2,"REUSE done");verify(all,0);b.check(b.rr(0x68)==K*VBYTES/32,"REUSE skipped Q/K");
 b.reg(0x54,8);b.check((b.run(2)&0xff04)==0x204,"stale reuse rejected");
 unsigned ids[]={3,5,11,16};std::memcpy(&b.mem[CB],ids,sizeof(ids));std::vector<std::pair<float,unsigned>> selected;
 for(unsigned x:ids)selected.push_back(all[x]);
 b.check(b.run(1)==2,"REINDEX done");verify(selected,4);b.check(b.rr(0x68)==H*3+1+4*3+4*VBYTES/32,"REINDEX physical read count");
 ids[1]=ids[0];std::memcpy(&b.mem[CB],ids,sizeof(ids));b.check((b.run(1)&0xff04)==0x304,"duplicate candidates rejected");
 ids[1]=N;std::memcpy(&b.mem[CB],ids,sizeof(ids));b.check((b.run(1)&0xff04)==0x304,"invalid candidate rejected");
 b.fail_read=true;b.check((b.run(0)&0xff04)==0x404,"DMA R error propagated");b.fail_read=false;
 b.mem[KB+64]=255;b.check((b.run(0)&0xff04)==0x504,"bad numeric format propagated");b.mem[KB+64]=127;
 b.fail_write=true;b.check((b.run(0)&0xff04)==0x404,"DMA B error propagated");b.fail_write=false;
 b.check(b.run(0)==2,"restart after error");verify(all,N);
 b.reg(8,2);b.check(b.rr(0x74)==0,"invalidate");
 b.check((b.run(2)&0xff04)==0x204,"invalidated reuse rejected");
 std::cout<<"PASS AXI256 FULL/REINDEX/REUSE, FP4 scores, position order, byte-exact KV, randomized DMA stalls, W-before-AW, held responses, stale epoch, bad candidates, R/B faults, numeric errors, restart; cycles="<<b.t<<"\n";
 return 0;
}catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<"\n";return 1;}}
