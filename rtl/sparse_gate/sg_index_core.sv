module sg_index_core #(
    parameter integer MAX_HEADS=32, TOPK_MAX=512, LANES=16,
    parameter integer HW=(TOPK_MAX<=1)?1:$clog2(TOPK_MAX)
) (
    input logic clk,rst_n,
    input logic q_we, output logic q_ready,
    input logic [5:0] q_head, input logic [6:0] q_offset, input logic [7:0] q_data,
    output logic q_load_error,
    input logic key_we, output logic key_ready,
    input logic [6:0] key_offset, input logic [7:0] key_data,
    output logic key_load_error,
    input logic job_valid, output logic job_ready,
    input logic [5:0] cfg_heads, input logic [9:0] cfg_k,
    input logic key_valid, output logic key_accept, input logic [31:0] key_index,
    output logic score_valid, input logic score_ready,
    output logic [31:0] score_index,score_value, output logic [7:0] score_error,
    input logic finish_valid, output logic finish_ready,
    output logic result_valid, input logic result_ready,
    output logic [31:0] result_index,result_score, output logic result_last,
    output logic done_valid, input logic done_ready, output logic [7:0] error_code,
    output logic busy,
    output logic [63:0] cycles, output logic [31:0] keys_scored,
    output logic [63:0] mac_terms
);
    import sg_fp32_pkg::*;
    typedef enum logic [4:0] {IDLE,CHECK_Q,READY,DOT,GCONVERT,GADD,HMUL,HADD,
        HEAP_BEGIN,HEAP_UP,HEAP_DOWN,SCORE,OUTPUTS,DONE} state_t;
    localparam integer QHW=(MAX_HEADS<=1)?1:$clog2(MAX_HEADS);
    state_t state;
    logic [7:0] qmem[0:MAX_HEADS-1][0:69];
    logic [69:0] q_loaded[0:MAX_HEADS-1];
    logic [7:0] kmem[0:67];logic [67:0] k_loaded;
    logic [31:0] heap_score[0:TOPK_MAX-1],heap_index[0:TOPK_MAX-1];
    logic [5:0] heads,head;
    logic [9:0] limit_k;
    logic [HW:0] heap_count;
    logic [HW-1:0] heap_pos,out_pos;
    logic [1:0] group_id;
    integer slice;
    logic signed [13:0] dot_sum,dot_batch;
    logic [31:0] head_dot,group_float,weighted,scan_score;
    logic [31:0] active_index,candidate_score;
    logic [32:0] group_result,group_add,head_product,head_add;
    integer dim,byte_addr,j,chosen,left_child,right_child,parent_pos;
    logic [3:0] qn,kn;
    logic signed [4:0] qi,ki;
    logic signed [9:0] prod;

    function automatic logic signed [4:0] fp4_int(input logic [3:0] x);
        logic signed [4:0] m;
        begin
            case(x[2:0])
                0:m=0;1:m=1;2:m=2;3:m=3;4:m=4;5:m=6;6:m=8;default:m=12;
            endcase
            fp4_int=x[3] ? -m : m;
        end
    endfunction
    always @* begin
        dot_batch=0;dim=0;byte_addr=0;qn=0;kn=0;qi=0;ki=0;prod=0;
        for(j=0;j<LANES;j=j+1) begin
            dim=int'(group_id)*32+slice*LANES+j;byte_addr=dim/2;
            if(dim%2==0) begin qn=qmem[QHW'(head)][byte_addr][3:0];kn=kmem[byte_addr][3:0];end
            else begin qn=qmem[QHW'(head)][byte_addr][7:4];kn=kmem[byte_addr][7:4];end
            qi=fp4_int(qn);ki=fp4_int(kn);prod=qi*ki;
            dot_batch=dot_batch+{{4{prod[9]}},prod};
        end
        group_result=sg_from_group(dot_sum,qmem[QHW'(head)][64+int'(group_id)],kmem[64+int'(group_id)]);
        group_add=sg_add(head_dot,group_float);
        head_product=sg_mul(head_dot[31]?32'b0:head_dot,{qmem[QHW'(head)][69],qmem[QHW'(head)][68],16'b0});
        head_add=sg_add(scan_score,weighted);
        parent_pos=(int'(heap_pos)-1)/2;
        left_child=int'(heap_pos)*2+1;right_child=left_child+1;chosen=left_child;
        if(right_child<int'(heap_count) &&
            sg_worse(heap_score[right_child],heap_index[right_child],heap_score[left_child],heap_index[left_child]))
            chosen=right_child;
    end
    assign q_ready=(state==READY) && (keys_scored==0);
    assign key_ready=(state==READY);
    assign q_load_error=q_we && q_ready && (int'(q_head)>=MAX_HEADS || q_offset>=70);
    assign key_load_error=key_we && key_ready && key_offset>=68;
    assign job_ready=(state==IDLE);
    assign key_accept=(state==READY) && !key_we && !q_we;
    assign finish_ready=(state==READY) && !key_we && !q_we && !key_valid;
    assign score_valid=(state==SCORE);
    assign score_index=active_index;assign score_value=candidate_score;
    assign score_error=error_code;
    assign result_valid=(state==OUTPUTS);
    assign result_index=heap_index[out_pos];assign result_score=heap_score[out_pos];
    assign result_last=(int'(out_pos)+1==int'(heap_count));
    assign done_valid=(state==DONE);assign busy=(state!=IDLE);

    integer h;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE;heads<=0;head<=0;limit_k<=0;heap_count<=0;heap_pos<=0;out_pos<=0;
            group_id<=0;slice<=0;dot_sum<=0;head_dot<=0;group_float<=0;weighted<=0;scan_score<=0;
            active_index<=0;candidate_score<=0;k_loaded<=0;error_code<=0;
            cycles<=0;keys_scored<=0;mac_terms<=0;
            for(h=0;h<MAX_HEADS;h=h+1)q_loaded[h]<=0;
        end else begin
            if(busy && state!=DONE) cycles<=cycles+1'b1;
            if(q_we && q_ready && !q_load_error) begin
                qmem[QHW'(q_head)][q_offset]<=q_data;q_loaded[QHW'(q_head)][q_offset]<=1;
            end
            if(key_we && key_ready && !key_load_error) begin
                kmem[key_offset]<=key_data;k_loaded[key_offset]<=1;
            end
            case(state)
                IDLE:if(job_valid && job_ready) begin
                    heads<=cfg_heads;limit_k<=cfg_k;heap_count<=0;head<=0;k_loaded<=0;
                    error_code<=0;cycles<=0;keys_scored<=0;mac_terms<=0;
                    for(h=0;h<MAX_HEADS;h=h+1)q_loaded[h]<=0;
                    if(cfg_heads==0 || int'(cfg_heads)>MAX_HEADS || cfg_k==0 || int'(cfg_k)>TOPK_MAX) begin
                        error_code<=1;state<=DONE;
                    end else state<=READY;
                end
                CHECK_Q:begin
                    if(q_loaded[QHW'(head)]!={70{1'b1}})begin error_code<=2;state<=SCORE;end
                    else if({qmem[QHW'(head)][69][6:0],qmem[QHW'(head)][68][7]}==8'hff)begin error_code<=5;state<=SCORE;end
                    else if(qmem[QHW'(head)][64]==255 || qmem[QHW'(head)][65]==255 || qmem[QHW'(head)][66]==255 || qmem[QHW'(head)][67]==255)begin
                        error_code<=4;state<=SCORE;
                    end else if(head+1==heads)begin head<=0;state<=DOT;end
                    else head<=head+1'b1;
                end
                READY:begin
                    if(key_valid && key_accept)begin
                        active_index<=key_index;candidate_score<=0;k_loaded<=0;
                        head<=0;group_id<=0;slice<=0;dot_sum<=0;head_dot<=0;scan_score<=0;
                        if(k_loaded!={68{1'b1}})begin error_code<=3;state<=SCORE;end
                        else if(kmem[64]==255 || kmem[65]==255 || kmem[66]==255 || kmem[67]==255)begin error_code<=4;state<=SCORE;end
                        else state<=CHECK_Q;
                    end else if(finish_valid && finish_ready)begin
                        out_pos<=0;if(heap_count==0)state<=DONE;else state<=OUTPUTS;
                    end
                end
                DOT:begin
                    dot_sum<=dot_sum+dot_batch;mac_terms<=mac_terms+64'(LANES);
                    if(slice==32/LANES-1)begin slice<=0;state<=GCONVERT;end
                    else slice<=slice+1;
                end
                GCONVERT:begin
                    if(group_result[32])begin error_code<=6;state<=SCORE;end
                    else begin group_float<=group_result[31:0];state<=GADD;end
                end
                GADD:begin
                    if(group_add[32])begin error_code<=6;state<=SCORE;end
                    else begin
                        head_dot<=group_add[31:0];dot_sum<=0;
                        if(group_id==3)state<=HMUL;
                        else begin group_id<=group_id+1'b1;state<=DOT;end
                    end
                end
                HMUL:begin
                    if(head_product[32])begin error_code<=6;state<=SCORE;end
                    else begin weighted<=head_product[31:0];state<=HADD;end
                end
                HADD:begin
                    if(head_add[32])begin error_code<=6;state<=SCORE;end
                    else begin
                        scan_score<=head_add[31:0];
                        if(head+1==heads)begin candidate_score<=head_add[31:0];keys_scored<=keys_scored+1'b1;state<=HEAP_BEGIN;end
                        else begin head<=head+1'b1;group_id<=0;head_dot<=0;dot_sum<=0;state<=DOT;end
                    end
                end
                HEAP_BEGIN:begin
                    if(heap_count<limit_k)begin heap_pos<=HW'(heap_count);heap_count<=heap_count+1'b1;state<=HEAP_UP;end
                    else if(sg_worse(heap_score[0],heap_index[0],candidate_score,active_index))begin heap_pos<=0;state<=HEAP_DOWN;end
                    else state<=SCORE;
                end
                HEAP_UP:begin
                    if(heap_pos!=0 && sg_worse(candidate_score,active_index,heap_score[parent_pos],heap_index[parent_pos]))begin
                        heap_score[heap_pos]<=heap_score[parent_pos];heap_index[heap_pos]<=heap_index[parent_pos];heap_pos<=HW'(parent_pos);
                    end else begin heap_score[heap_pos]<=candidate_score;heap_index[heap_pos]<=active_index;state<=SCORE;end
                end
                HEAP_DOWN:begin
                    if(left_child<int'(heap_count) && sg_worse(heap_score[chosen],heap_index[chosen],candidate_score,active_index))begin
                        heap_score[heap_pos]<=heap_score[chosen];heap_index[heap_pos]<=heap_index[chosen];heap_pos<=HW'(chosen);
                    end else begin heap_score[heap_pos]<=candidate_score;heap_index[heap_pos]<=active_index;state<=SCORE;end
                end
                SCORE:if(score_ready)begin if(error_code!=0)state<=DONE;else state<=READY;end
                OUTPUTS:if(result_ready)begin if(result_last)state<=DONE;else out_pos<=out_pos+1'b1;end
                DONE:if(done_ready)state<=IDLE;
                default:state<=IDLE;
            endcase
        end
    end
endmodule
