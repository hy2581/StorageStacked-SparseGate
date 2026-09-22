// Memory-side CSA2 index/selection/gather engine. See docs/sparse_gate/interface.md.
module sparse_gate_axi #(
 parameter logic [63:0] MEM_BASE=64'h90000000,
 parameter logic [63:0] MEM_BYTES=64'h100000,
 parameter logic [63:0] REG_BASE=64'h900f0000
)(input logic clk,rst_n,
 input logic [15:0] s_axi_awid, input logic [63:0] s_axi_awaddr,
 input logic [7:0] s_axi_awlen, input logic [2:0] s_axi_awsize,
 input logic [1:0] s_axi_awburst, input logic s_axi_awvalid, output logic s_axi_awready,
 input logic [255:0] s_axi_wdata, input logic [31:0] s_axi_wstrb,
 input logic s_axi_wlast, s_axi_wvalid, output logic s_axi_wready,
 output logic [15:0] s_axi_bid, output logic [1:0] s_axi_bresp,
 output logic s_axi_bvalid, input logic s_axi_bready,
 input logic [15:0] s_axi_arid, input logic [63:0] s_axi_araddr,
 input logic [7:0] s_axi_arlen, input logic [2:0] s_axi_arsize,
 input logic [1:0] s_axi_arburst, input logic s_axi_arvalid, output logic s_axi_arready,
 output logic [15:0] s_axi_rid, output logic [255:0] s_axi_rdata,
 output logic [1:0] s_axi_rresp, output logic s_axi_rlast, s_axi_rvalid,
 input logic s_axi_rready,
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
 localparam integer MAX_K=512;
 logic [31:0] cfg[0:31];
 wire [63:0] qbase={cfg[5],cfg[4]},kbase={cfg[7],cfg[6]};
 wire [63:0] cbase={cfg[9],cfg[8]},obase={cfg[11],cfg[10]};
 wire [63:0] kvbase={cfg[13],cfg[12]},gbase={cfg[15],cfg[14]};
 logic busy,done_flag,error_flag,cache_valid;
 logic [7:0] error_code;
 logic [63:0] cycles;
 logic [31:0] score_count,result_count;
 logic start_pulse,invalidate_pulse,illegal_pulse;
 logic [31:0] dma_reads,dma_writes;
 logic [31:0] cache_idx[0:MAX_K-1],cache_score[0:MAX_K-1];
 logic [31:0] saved_context,saved_epoch,saved_nkeys,saved_k,saved_heads;
 logic [63:0] saved_qbase,saved_kbase;
 // Register channel: one independently buffered AW and W, one read burst.
 logic aw_have,w_have,write_drain;
 logic [63:0] aw_addr; logic [15:0] aw_id;
 logic [7:0] aw_len;logic [2:0] aw_size;logic [1:0] aw_burst;
 logic [255:0] w_data;logic [31:0] w_strb;logic w_last;
 logic [7:0] read_left; logic [63:0] read_addr;
 integer j,regnum,lane; logic bad_write;
 function automatic [31:0] reg_value(input integer n);
  case(n)
   0:reg_value=32'h53474154;
   1:reg_value={16'b0,error_code,5'b0,error_flag,done_flag,busy};
   2:reg_value=0;
   23:reg_value=result_count;
   24:reg_value=cycles[31:0];25:reg_value=cycles[63:32];
   26:reg_value=dma_reads;27:reg_value=dma_writes;
   28:reg_value=score_count;29:reg_value={31'b0,cache_valid};
   default:reg_value=(n>=3&&n<=22)?cfg[n]:0;
  endcase
 endfunction
 function automatic [255:0] reg_line(input logic [63:0] a);
  logic [255:0] v;integer n;
  begin
   v=0;for(n=0;n<8;n=n+1) v[n*32+:32]=reg_value(integer'((a-REG_BASE)&64'hfe0)/4+n);
   reg_line=v;
  end
 endfunction
 assign s_axi_awready=rst_n&&!aw_have&&!s_axi_bvalid&&!write_drain;
 assign s_axi_wready=rst_n&&!w_have&&!s_axi_bvalid;
 assign s_axi_arready=rst_n&&!s_axi_rvalid;
 always_ff @(posedge clk) begin
  if(!rst_n) begin
   aw_have<=0;w_have<=0;write_drain<=0;aw_addr<=0;aw_id<=0;aw_len<=0;aw_size<=0;aw_burst<=0;
   w_data<=0;w_strb<=0;w_last<=0;
   s_axi_bvalid<=0;s_axi_bid<=0;s_axi_bresp<=0;
   s_axi_rvalid<=0;s_axi_rid<=0;s_axi_rdata<=0;s_axi_rresp<=0;s_axi_rlast<=0;
   read_left<=0;read_addr<=0;start_pulse<=0;invalidate_pulse<=0;illegal_pulse<=0;
   for(j=0;j<32;j=j+1) cfg[j]<=0;
  end else begin
   start_pulse<=0;invalidate_pulse<=0;illegal_pulse<=0;
   if(s_axi_bvalid&&s_axi_bready) s_axi_bvalid<=0;
   if(s_axi_awvalid&&s_axi_awready) begin
    aw_have<=1;aw_addr<=s_axi_awaddr;aw_id<=s_axi_awid;
    aw_len<=s_axi_awlen;aw_size<=s_axi_awsize;aw_burst<=s_axi_awburst;
   end
   if(s_axi_wvalid&&s_axi_wready) begin
    w_have<=1;w_data<=s_axi_wdata;w_strb<=s_axi_wstrb;w_last<=s_axi_wlast;
   end
   if(write_drain&&w_have) begin
    w_have<=0;
    if(w_last) begin write_drain<=0;aw_have<=0;s_axi_bvalid<=1;s_axi_bresp<=2;s_axi_bid<=aw_id;end
   end else if(aw_have&&w_have&&!s_axi_bvalid) begin
    bad_write=busy||aw_len!=0||!w_last||aw_size>5||aw_burst!=1||
      aw_addr[63:12]!=REG_BASE[63:12]||((aw_addr&((64'd1<<aw_size)-1))!=0);
    // WSTRB must only name lanes covered by AWSIZE/address.
    for(j=0;j<32;j=j+1) if(w_strb[j]) begin
     regnum=integer'((aw_addr-REG_BASE)&64'hfe0)/4+j/4;
     if(j<integer'(aw_addr[4:0])||j>=integer'(aw_addr[4:0])+(1<<aw_size)||
        !((regnum>=3&&regnum<=22)||regnum==2)) bad_write=1;
    end
    if(!bad_write) begin
     for(j=0;j<32;j=j+1) if(w_strb[j]) begin
      regnum=integer'((aw_addr-REG_BASE)&64'hfe0)/4+j/4;
      if(regnum>=3&&regnum<=22) cfg[regnum][(j%4)*8+:8]<=w_data[j*8+:8];
     end
     if(aw_addr[11:5]==0 && |w_strb[11:8]) begin
      if(w_strb[11:8]!=4'hf) begin bad_write=1;illegal_pulse<=1;end
      else case(w_data[64+:32])
       1:start_pulse<=1;
       2:invalidate_pulse<=1;
       default:begin bad_write=1;illegal_pulse<=1;end
      endcase
     end
    end
    w_have<=0;
    if(!w_last) write_drain<=1;
    else begin aw_have<=0;s_axi_bvalid<=1;s_axi_bid<=aw_id;s_axi_bresp<=bad_write?2:0;end
   end
   if(s_axi_arvalid&&s_axi_arready) begin
    s_axi_rvalid<=1;s_axi_rid<=s_axi_arid;read_left<=s_axi_arlen;
    s_axi_rlast<=s_axi_arlen==0;read_addr<=s_axi_araddr;
    s_axi_rresp<=(s_axi_arlen!=0||s_axi_arsize>5||s_axi_arburst!=1||
     s_axi_araddr[63:12]!=REG_BASE[63:12]||((s_axi_araddr&((64'd1<<s_axi_arsize)-1))!=0))?2:0;
    s_axi_rdata<=reg_line(s_axi_araddr);
   end else if(s_axi_rvalid&&s_axi_rready) begin
    if(read_left==0) s_axi_rvalid<=0;
    else begin read_left<=read_left-1;s_axi_rlast<=read_left==1;s_axi_rdata<=0;end
   end
  end
 end

 logic dma_req_valid,dma_req_ready,dma_req_write,dma_done,dma_error;
 logic [63:0] dma_addr;logic [255:0] dma_data,dma_read_data;
 logic [31:0] dma_strb;logic clear_counts;
 sparse_gate_dma #(.MEM_BASE(MEM_BASE),.MEM_BYTES(MEM_BYTES),.REG_BASE(REG_BASE)) dma(
 .clk,.rst_n,.req_valid(dma_req_valid),.req_ready(dma_req_ready),.req_write(dma_req_write),
 .req_addr(dma_addr),.req_data(dma_data),.req_strb(dma_strb),.done(dma_done),.error(dma_error),
 .read_data(dma_read_data),.read_beats(dma_reads),.write_beats(dma_writes),.clear_counts,
 .m_axi_awid,.m_axi_awaddr,.m_axi_awlen,.m_axi_awsize,.m_axi_awburst,.m_axi_awvalid,.m_axi_awready,
 .m_axi_wdata,.m_axi_wstrb,.m_axi_wlast,.m_axi_wvalid,.m_axi_wready,
 .m_axi_bid,.m_axi_bresp,.m_axi_bvalid,.m_axi_bready,
 .m_axi_arid,.m_axi_araddr,.m_axi_arlen,.m_axi_arsize,.m_axi_arburst,.m_axi_arvalid,.m_axi_arready,
 .m_axi_rid,.m_axi_rdata,.m_axi_rresp,.m_axi_rlast,.m_axi_rvalid,.m_axi_rready);

 typedef enum logic [5:0] {S_IDLE,S_START,S_JOB,S_QREQ,S_QWAIT,S_QLOAD,
 S_NEXT_KEY,S_CREQ,S_CWAIT,S_CSELECT,S_KREQ,S_KWAIT,S_KLOAD,S_KEYSTART,S_KEYWAIT,
 S_END,S_RESULTS,S_INSERT,S_OUTREQ,S_OUTWAIT,S_GREAD,S_GWAIT,S_GWRITE,S_GWRITEWAIT,
 S_ADVANCE,S_FINISH,S_ERROR} engine_state;
 engine_state es;
 logic core_job_start,core_job_ready,core_load_ready;
 logic q_we,key_we;logic [5:0] q_head;logic [6:0] q_offset,key_offset;logic [7:0] q_data,key_data;
 logic core_key_start,core_key_ready,core_key_done,core_key_done_ready,core_key_error;
 logic [31:0] core_key_index,core_key_done_index,core_key_score;
 logic core_end_scan,core_end_ready,core_result_valid,core_result_ready,core_result_last;
 logic [31:0] core_result_index,core_result_score;
 logic core_done,core_error;
 // Core pin names are kept here; generated-model adapters never compute scores.
 logic core_q_ready,core_k_ready;logic [7:0] core_score_error,core_job_error;
 wire core_reset_n=rst_n && es!=S_ERROR;
 assign core_load_ready=(es==S_QLOAD)?core_q_ready:core_k_ready;
 assign core_key_error=core_score_error!=0;
 assign core_error=core_done && core_job_error!=0;
 sg_index_core core(
 .clk,.rst_n(core_reset_n),.job_valid(core_job_start),.job_ready(core_job_ready),
 .cfg_heads(cfg[19][5:0]),.cfg_k(cfg[18][9:0]),
 .q_we,.q_ready(core_q_ready),.q_head,.q_offset,.q_data,.q_load_error(),
 .key_we,.key_ready(core_k_ready),.key_offset,.key_data,.key_load_error(),
 .key_valid(core_key_start),.key_accept(core_key_ready),.key_index(core_key_index),
 .score_valid(core_key_done),.score_ready(core_key_done_ready),.score_index(core_key_done_index),
 .score_value(core_key_score),.score_error(core_score_error),
 .finish_valid(core_end_scan),.finish_ready(core_end_ready),
 .result_valid(core_result_valid),.result_ready(core_result_ready),
 .result_index(core_result_index),.result_score(core_result_score),.result_last(core_result_last),
 .done_valid(core_done),.done_ready(1'b1),.error_code(core_job_error),
 .busy(),.cycles(),.keys_scored(),.mac_terms());


 logic [5:0] head_no;logic [1:0] line_no;logic [5:0] byte_no;
 logic [255:0] line_data,candidate_line,gather_line;
 logic [31:0] scan_no,current_key,previous_candidate;
 logic [9:0] insert_pos,output_no;
 logic [31:0] insert_idx,insert_score;logic insert_last;
 logic [31:0] gather_offset;
 function automatic logic region_ok(input logic [63:0] a,n);
  logic [64:0] e;
  begin e={1'b0,a}+{1'b0,n};region_ok=n!=0 && a>=MEM_BASE && !e[64] &&
   e<={1'b0,MEM_BASE}+{1'b0,MEM_BYTES} && (e<={1'b0,REG_BASE} || a>=REG_BASE+4096);end
 endfunction
 function automatic logic separate(input logic [63:0] a,n,b,m);
  separate=(a+n<=b)||(b+m<=a);
 endfunction
 wire [63:0] qbytes=64'(cfg[19])*96,kbytes=64'(cfg[16])*96;
 wire [63:0] cbytes=((64'(cfg[17])+7)>>3)*32;
 wire [31:0] scan_count=(cfg[3]==1)?cfg[17]:cfg[16];
 wire [63:0] expected_count=(scan_count<cfg[18])?64'(scan_count):64'(cfg[18]);
 // REUSE inherits the cached result count, which may be less than configured K.
 wire [63:0] out_count=(cfg[3]==2)?64'(result_count):expected_count;
 wire [63:0] obytes=out_count*32,vbytes=64'(cfg[16])*64'(cfg[22]),gbytes=out_count*64'(cfg[22]);
 wire ranges_ok=region_ok(qbase,qbytes)&&region_ok(kbase,kbytes)&&region_ok(obase,obytes)&&
 separate(obase,obytes,qbase,qbytes)&&separate(obase,obytes,kbase,kbytes)&&
 (cfg[3]!=1||(region_ok(cbase,cbytes)&&separate(obase,obytes,cbase,cbytes)))&&
 (cfg[22]==0||(region_ok(kvbase,vbytes)&&region_ok(gbase,gbytes)&&
  separate(obase,obytes,kvbase,vbytes)&&separate(obase,obytes,gbase,gbytes)&&
  separate(gbase,gbytes,qbase,qbytes)&&separate(gbase,gbytes,kbase,kbytes)&&
  separate(gbase,gbytes,kvbase,vbytes)&&
  (cfg[3]!=1||separate(gbase,gbytes,cbase,cbytes))));
 wire config_ok=(ranges_ok && cfg[3]<=2 && cfg[16]>0 && cfg[16]<=65536 &&
 cfg[18]>0&&cfg[18]<=512&&cfg[19]>0&&cfg[19]<=32 &&
 (cfg[3]!=1||(cfg[17]>0&&cfg[17]<=cfg[16]))&&cfg[22]<=4096&&cfg[22][4:0]==0&&
 qbase[4:0]==0&&kbase[4:0]==0&&cbase[4:0]==0&&obase[4:0]==0&&kvbase[4:0]==0&&gbase[4:0]==0);
 wire reuse_ok=cache_valid&&saved_context==cfg[20]&&saved_epoch==cfg[21]&&
 saved_nkeys==cfg[16]&&saved_k==cfg[18]&&saved_heads==cfg[19]&&saved_qbase==qbase&&saved_kbase==kbase;
 always_comb begin
  core_job_start=es==S_JOB;core_key_start=es==S_KEYSTART;core_key_index=current_key;
  core_key_done_ready=es==S_KEYWAIT;core_end_scan=es==S_END;
  core_result_ready=es==S_RESULTS;
  q_we=es==S_QLOAD&&core_load_ready&&(integer'(line_no)*32+integer'(byte_no)<70);
  q_head=head_no;q_offset={line_no,5'b0}+{1'b0,byte_no};q_data=line_data[byte_no*8+:8];
  key_we=es==S_KLOAD&&core_load_ready&&(integer'(line_no)*32+integer'(byte_no)<68);
  key_offset={line_no,5'b0}+{1'b0,byte_no};key_data=line_data[byte_no*8+:8];
  dma_req_valid=0;dma_req_write=0;dma_addr=0;dma_data=0;dma_strb=32'hffffffff;
  clear_counts=es==S_START;
  case(es)
   S_QREQ:begin dma_req_valid=1;dma_addr=qbase+64'(head_no)*96+64'(line_no)*32;end
   S_CREQ:begin dma_req_valid=1;dma_addr=cbase+64'(scan_no[31:3])*32;end
   S_KREQ:begin dma_req_valid=1;dma_addr=kbase+64'(current_key)*96+64'(line_no)*32;end
   S_OUTREQ:begin dma_req_valid=1;dma_req_write=1;dma_addr=obase+64'(output_no)*32;
    dma_data={192'b0,cache_score[output_no[8:0]],cache_idx[output_no[8:0]]};end
   S_GREAD:begin dma_req_valid=1;dma_addr=kvbase+64'(cache_idx[output_no[8:0]])*64'(cfg[22])+64'(gather_offset);end
   S_GWRITE:begin dma_req_valid=1;dma_req_write=1;dma_addr=gbase+64'(output_no)*64'(cfg[22])+64'(gather_offset);dma_data=gather_line;end
   default:begin end
  endcase
 end
 always_ff @(posedge clk) begin
  if(!rst_n) begin
   es<=S_IDLE;busy<=0;done_flag<=0;error_flag<=0;error_code<=0;cache_valid<=0;
   cycles<=0;score_count<=0;result_count<=0;head_no<=0;line_no<=0;byte_no<=0;
   scan_no<=0;current_key<=0;previous_candidate<=0;line_data<=0;candidate_line<=0;gather_line<=0;
   insert_pos<=0;output_no<=0;insert_idx<=0;insert_score<=0;insert_last<=0;gather_offset<=0;
   saved_context<=0;saved_epoch<=0;saved_nkeys<=0;saved_k<=0;saved_heads<=0;saved_qbase<=0;saved_kbase<=0;
  end else begin
   if(busy) cycles<=cycles+1;
   if(invalidate_pulse) cache_valid<=0;
   if(illegal_pulse&&!busy) begin done_flag<=0;error_flag<=1;error_code<=6;end
   case(es)
    S_IDLE:if(start_pulse) begin busy<=1;done_flag<=0;error_flag<=0;error_code<=0;cycles<=0;score_count<=0;es<=S_START;end
    S_START:begin
     if(cfg[3]==2&&!reuse_ok) begin error_code<=2;es<=S_ERROR;end
     else if(!config_ok) begin error_code<=1;es<=S_ERROR;end
     else if(cfg[3]==2) begin
      if(!reuse_ok) begin error_code<=2;es<=S_ERROR;end
      else begin output_no<=0;es<=S_OUTREQ;end
     end else begin cache_valid<=0;result_count<=0;head_no<=0;line_no<=0;scan_no<=0;es<=S_JOB;end
    end
    S_JOB:if(core_job_ready) es<=S_QREQ;
    S_QREQ:if(dma_req_ready) es<=S_QWAIT;
    S_QWAIT:if(dma_done) begin
     if(dma_error) begin error_code<=4;es<=S_ERROR;end
     else begin line_data<=dma_read_data;byte_no<=0;es<=S_QLOAD;end
    end
    S_QLOAD:if(core_load_ready) begin
     if(byte_no==31) begin
      byte_no<=0;
      if(line_no==2) begin line_no<=0;
       if(32'(head_no)+1==cfg[19]) es<=S_NEXT_KEY;
       else begin head_no<=head_no+1;es<=S_QREQ;end
      end else begin line_no<=line_no+1;es<=S_QREQ;end
     end else byte_no<=byte_no+1;
    end
    S_NEXT_KEY:begin
     if(scan_no==(cfg[3]==1?cfg[17]:cfg[16])) es<=S_END;
     else if(cfg[3]==1) es<=scan_no[2:0]==0?S_CREQ:S_CSELECT;
     else begin current_key<=scan_no;line_no<=0;es<=S_KREQ;end
    end
    S_CREQ:if(dma_req_ready) es<=S_CWAIT;
    S_CWAIT:if(dma_done) begin
     if(dma_error) begin error_code<=4;es<=S_ERROR;end
     else begin candidate_line<=dma_read_data;es<=S_CSELECT;end
    end
    S_CSELECT:begin
     if(candidate_line[scan_no[2:0]*32+:32]>=cfg[16]||
        (scan_no!=0&&candidate_line[scan_no[2:0]*32+:32]<=previous_candidate)) begin error_code<=3;es<=S_ERROR;end
     else begin current_key<=candidate_line[scan_no[2:0]*32+:32];
      previous_candidate<=candidate_line[scan_no[2:0]*32+:32];line_no<=0;es<=S_KREQ;end
    end
    S_KREQ:if(dma_req_ready) es<=S_KWAIT;
    S_KWAIT:if(dma_done) begin
     if(dma_error) begin error_code<=4;es<=S_ERROR;end
     else begin line_data<=dma_read_data;byte_no<=0;es<=S_KLOAD;end
    end
    S_KLOAD:if(core_load_ready) begin
     if(byte_no==31) begin byte_no<=0;
      if(line_no==2) begin line_no<=0;es<=S_KEYSTART;end
      else begin line_no<=line_no+1;es<=S_KREQ;end
     end else byte_no<=byte_no+1;
    end
    S_KEYSTART:if(core_key_ready) es<=S_KEYWAIT;
    S_KEYWAIT:if(core_key_done) begin
     if(core_key_error) begin error_code<=5;es<=S_ERROR;end
     else begin score_count<=score_count+1;scan_no<=scan_no+1;es<=S_NEXT_KEY;end
    end
    S_END:if(core_end_ready) es<=S_RESULTS;
    S_RESULTS:begin
     if(core_error) begin error_code<=5;es<=S_ERROR;end
     else if(core_result_valid) begin insert_idx<=core_result_index;insert_score<=core_result_score;
      insert_last<=core_result_last;insert_pos<=result_count[9:0];es<=S_INSERT;end
    end
    S_INSERT:begin
     if(insert_pos>0&&cache_idx[(insert_pos[8:0]-9'd1)]>insert_idx) begin
      cache_idx[insert_pos[8:0]]<=cache_idx[(insert_pos[8:0]-9'd1)];cache_score[insert_pos[8:0]]<=cache_score[(insert_pos[8:0]-9'd1)];insert_pos<=insert_pos-1;
     end else begin cache_idx[insert_pos[8:0]]<=insert_idx;cache_score[insert_pos[8:0]]<=insert_score;result_count<=result_count+1;
      if(insert_last) begin output_no<=0;es<=S_OUTREQ;end else es<=S_RESULTS;
     end
    end
    S_OUTREQ:if(dma_req_ready) es<=S_OUTWAIT;
    S_OUTWAIT:if(dma_done) begin
     if(dma_error) begin error_code<=4;es<=S_ERROR;end
     else if(cfg[22]==0) es<=S_ADVANCE;
     else begin gather_offset<=0;es<=S_GREAD;end
    end
    S_GREAD:if(dma_req_ready) es<=S_GWAIT;
    S_GWAIT:if(dma_done) begin
     if(dma_error) begin error_code<=4;es<=S_ERROR;end
     else begin gather_line<=dma_read_data;es<=S_GWRITE;end
    end
    S_GWRITE:if(dma_req_ready) es<=S_GWRITEWAIT;
    S_GWRITEWAIT:if(dma_done) begin
     if(dma_error) begin error_code<=4;es<=S_ERROR;end
     else if(gather_offset+32==cfg[22]) es<=S_ADVANCE;
     else begin gather_offset<=gather_offset+32;es<=S_GREAD;end
    end
    S_ADVANCE:begin
     if(32'(output_no)+1==result_count) es<=S_FINISH;
     else begin output_no<=output_no+1;es<=S_OUTREQ;end
    end
    S_FINISH:begin
     busy<=0;done_flag<=1;cache_valid<=1;es<=S_IDLE;
     saved_context<=cfg[20];saved_epoch<=cfg[21];saved_nkeys<=cfg[16];saved_k<=cfg[18];
     saved_heads<=cfg[19];saved_qbase<=qbase;saved_kbase<=kbase;
    end
    S_ERROR:begin busy<=0;done_flag<=0;error_flag<=1;cache_valid<=0;es<=S_IDLE;end
    default:es<=S_IDLE;
   endcase
  end
 end
endmodule
