module tb_lane_sweep #(parameter integer LANES=16);
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,q_we=0,key_we=0,job_valid=0,key_valid=0,score_ready=0,finish_valid=0,result_ready=0,done_ready=0;
    wire q_ready,key_ready,job_ready,key_accept,score_valid,finish_ready,result_valid,result_last,done_valid,busy,q_load_error,key_load_error;
    reg [5:0] q_head=0,cfg_heads=0;
    reg [6:0] q_offset=0,key_offset=0;
    reg [7:0] q_data=0,key_data=0;
    reg [9:0] cfg_k=0;
    reg [31:0] key_index=0;
    wire [31:0] score_index,score_value,result_index,result_score,keys_scored;
    wire [7:0] score_error,error_code;
    wire [63:0] cycles,mac_terms;
    sg_index_core #(.LANES(LANES)) dut(.*);
    reg [4095:0] filename;
    integer fd,rc,op,case_id,holds,received,watchdog,seed=71,j;
    reg [31:0] a,b,c,d,saved_index,saved_value;
    reg saved_last;
    longint unsigned phase_ready=0,phase_compute=0,phase_heap=0,phase_score=0,phase_output=0,q_bytes=0,k_bytes=0;
    always @(posedge clk) begin
        if(!rst_n || (job_valid && job_ready)) begin
            phase_ready=0;phase_compute=0;phase_heap=0;phase_score=0;phase_output=0;q_bytes=0;k_bytes=0;
        end else if(busy && !done_valid)begin
            case(dut.state)
                2:phase_ready=phase_ready+1;
                1,3,4,5,6,7:phase_compute=phase_compute+1;
                8,9,10:phase_heap=phase_heap+1;
                11:phase_score=phase_score+1;
                12:phase_output=phase_output+1;
                default:$fatal(1,"unclassified active state");
            endcase
            if(q_we && q_ready)q_bytes=q_bytes+1;
            if(key_we && key_ready)k_bytes=k_bytes+1;
        end
    end
    task edge_done;begin @(posedge clk);#1;end endtask
    task await_done(input reg[7:0] expected);
        begin
            watchdog=0;
            while(!done_valid)begin @(negedge clk);watchdog=watchdog+1;if(watchdog>10000)$fatal(1,"done timeout");end
            if(error_code!==expected)$fatal(1,"done error expected=%d actual=%d",expected,error_code);
            $display("PHASE %0d %0d %0d %0d %0d %0d %0d %0d",case_id,phase_ready,phase_compute,phase_heap,phase_score,phase_output,q_bytes,k_bytes);
            $display("MEASURE %0d %0d %0d %0d %0d",case_id,cycles,keys_scored,mac_terms,error_code);
            repeat(3)begin @(negedge clk);if(!done_valid || error_code!==expected)$fatal(1,"done unstable");end
            done_ready=1;edge_done();done_ready=0;
        end
    endtask
    initial begin
        if(!$value$plusargs("commands=%s",filename))$fatal(1,"missing commands");
        fd=$fopen(filename,"r");if(!fd)$fatal(1,"open commands");
        repeat(2)edge_done();rst_n=1;
        while(!$feof(fd))begin
            rc=$fscanf(fd,"%d %h %h %h %h\n",op,a,b,c,d);
            if(rc==5)begin
                case(op)
                    0:begin
                        @(negedge clk);rst_n=0;q_we=0;key_we=0;job_valid=0;key_valid=0;finish_valid=0;score_ready=0;result_ready=0;done_ready=0;
                        repeat(2)edge_done();rst_n=1;edge_done();
                        if(busy || result_valid || score_valid || done_valid)$fatal(1,"reset did not clear outputs");
                    end
                    1:begin
                        @(negedge clk);cfg_heads=a[5:0];cfg_k=b[9:0];case_id=c;job_valid=1;#1;
                        if(!job_ready)$fatal(1,"job not ready");edge_done();job_valid=0;
                    end
                    2:begin
                        @(negedge clk);q_head=a[5:0];q_offset=b[6:0];q_data=c[7:0];q_we=1;#1;
                        if(!q_ready || q_load_error!==d[0])$fatal(1,"q handshake/error");edge_done();q_we=0;
                    end
                    3:begin
                        @(negedge clk);key_offset=a[6:0];key_data=b[7:0];key_we=1;#1;
                        if(!key_ready || key_load_error!==c[0])$fatal(1,"key handshake/error");edge_done();key_we=0;
                    end
                    4:begin
                        @(negedge clk);key_index=a;key_valid=1;#1;if(!key_accept)$fatal(1,"key not accepted");edge_done();key_valid=0;
                        watchdog=0;
                        while(!score_valid)begin
                            @(negedge clk);watchdog=watchdog+1;
                            if(key_ready || key_accept || q_ready || result_valid)$fatal(1,"early ready/result while computing");
                            if(watchdog>10000)$fatal(1,"score timeout");
                        end
                        if(score_index!==a || score_error!==c[7:0] || (c==0 && score_value!==b))
                            $fatal(1,"score case=%0d index=%0d expected=%h/%d got=%h/%d",case_id,a,b,c,score_value,score_error);
                        saved_index=score_index;saved_value=score_value;
                        holds=($random(seed)&7)+1;
                        repeat(holds)begin @(negedge clk);if(!score_valid || score_index!==saved_index || score_value!==saved_value)$fatal(1,"score unstable");end
                        $display("SCORE %0d %0d %08h %0d",case_id,score_index,score_value,score_error);
                        score_ready=1;edge_done();score_ready=0;
                    end
                    5:begin
                        @(negedge clk);finish_valid=1;#1;if(!finish_ready)$fatal(1,"finish not ready");edge_done();finish_valid=0;received=0;
                        while(!done_valid)begin
                            @(negedge clk);
                            if(result_valid)begin
                                saved_index=result_index;saved_value=result_score;saved_last=result_last;
                                holds=($random(seed)&7)+1;
                                repeat(holds)begin @(negedge clk);if(!result_valid || result_index!==saved_index || result_score!==saved_value || result_last!==saved_last)$fatal(1,"result unstable");end
                                if(result_last !== (received+1==a))$fatal(1,"bad result_last");
                                $display("RESULT %0d %0d %08h",case_id,result_index,result_score);
                                result_ready=1;edge_done();result_ready=0;received=received+1;
                            end else if(!done_valid)$fatal(1,"unexpected result gap");
                        end
                        if(received!=a)$fatal(1,"result count");await_done(0);
                    end
                    6:await_done(a[7:0]);
                    // Abort a real in-flight key with reset after a bounded cycle count.
                    7:begin
                        @(negedge clk);key_index=a;key_valid=1;#1;if(!key_accept)$fatal(1,"abort key not ready");edge_done();key_valid=0;
                        repeat(b)edge_done();@(negedge clk);rst_n=0;repeat(2)edge_done();rst_n=1;edge_done();
                        if(busy || result_valid || score_valid || done_valid)$fatal(1,"abort reset leaked result");
                    end
                    default:$fatal(1,"unknown command %d",op);
                endcase
            end else if(rc!=-1)$fatal(1,"parse %d",rc);
        end
        $display("CORE_STREAM_PASS");$finish;
    end
    initial begin #1000000000;$fatal(1,"global watchdog");end
endmodule
