module tb_fp32;
    import sg_fp32_pkg::*;
    integer fd,rc,op,n,errors;
    reg [31:0] a,b,c;
    reg [32:0] expected,actual;
    reg [4095:0] filename;
    initial begin
        if(!$value$plusargs("vectors=%s",filename))$fatal(1,"missing vectors");
        fd=$fopen(filename,"r");if(!fd)$fatal(1,"open vectors");
        n=0;errors=0;
        while(!$feof(fd))begin
            rc=$fscanf(fd,"%d %h %h %h %h\n",op,a,b,c,expected);
            if(rc==5)begin
                case(op)
                    0:actual=sg_add(a,b);
                    1:actual=sg_mul(a,b);
                    2:actual=sg_from_group(a[13:0],b[7:0],c[7:0]);
                    default:$fatal(1,"bad op");
                endcase
                if(actual[32]!==expected[32] || (!expected[32] && actual[31:0]!==expected[31:0]))begin
                    $display("FAIL %d %h %h %h expected=%h got=%h",op,a,b,c,expected,actual);
                    errors=errors+1;if(errors==20)$fatal(1,"too many errors");
                end
                n=n+1;
            end else if(rc!=-1)$fatal(1,"parse rc=%d",rc);
        end
        $display("FP32_CASES %0d ERRORS %0d",n,errors);
        if(errors)$fatal(1,"numeric failure");
        $finish;
    end
endmodule
