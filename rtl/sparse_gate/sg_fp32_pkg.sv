package sg_fp32_pkg;
    // Every arithmetic result is {overflow, IEEE binary32}. Inputs must be finite.
    // RNE, gradual underflow. No real/shortreal/DPI or non-synthesizable arithmetic.
    function automatic [32:0] sg_pack48(input logic sign,
                                      input logic [47:0] mag,
                                      input integer binary_exp);
        integer lead, exponent, shift_count, j;
        logic [48:0] rounded;
        logic guard_bit, sticky;
        logic [7:0] ef;
        begin
            lead=-1;
            for(j=0;j<48;j=j+1) if(mag[j]) lead=j;
            rounded=0;guard_bit=0;sticky=0;ef=0;
            sg_pack48={1'b0,sign,31'b0};
            if(lead>=0) begin
                exponent=binary_exp+lead;
                shift_count=lead-23;
                if(exponent < -126) begin
                    shift_count=shift_count+(-126-exponent);
                    exponent=-126;
                end
                if(shift_count>0) begin
                    if(shift_count<49) rounded={1'b0,mag} >> shift_count;
                    for(j=0;j<48;j=j+1) begin
                        if(j==shift_count-1) guard_bit=mag[j];
                        if(j<shift_count-1) sticky=sticky|mag[j];
                    end
                    if(guard_bit && (sticky || rounded[0])) rounded=rounded+1'b1;
                end else rounded={1'b0,mag} << (-shift_count);
                if(rounded[24]) begin rounded=rounded>>1; exponent=exponent+1; end
                if(exponent>127) sg_pack48={1'b1,sign,8'hff,23'b0};
                else begin
                    if(rounded[23]) ef=8'(exponent+127);
                    else ef=0;
                    sg_pack48={1'b0,sign,ef,rounded[22:0]};
                end
            end
        end
    endfunction

    function automatic [32:0] sg_from_group(input logic signed [13:0] dot,
                                            input logic [7:0] qs,ks);
        logic [13:0] magnitude;
        integer exponent;
        begin
            magnitude=dot[13] ? $unsigned(-dot) : $unsigned(dot);
            exponent=int'({1'b0,qs})+int'({1'b0,ks})-256;
            sg_from_group=sg_pack48(dot[13],{34'b0,magnitude},exponent);
        end
    endfunction

    function automatic [27:0] sg_shr_jam28(input logic [27:0] a,input integer amount);
        logic [27:0] z;
        logic sticky;
        integer i;
        begin
            z=(amount>=28) ? 28'b0 : (a >> amount);
            sticky=0;
            for(i=0;i<28;i=i+1) if(i<amount) sticky=sticky|a[i];
            z[0]=z[0]|sticky;sg_shr_jam28=z;
        end
    endfunction

    function automatic [32:0] sg_add(input logic [31:0] a,b);
        logic [23:0] sa,sb;
        logic [27:0] big,smaller,value;
        logic sign_big,sign_small,sign_out;
        integer ea,eb,exponent;
        begin
            sa={|a[30:23],a[22:0]};sb={|b[30:23],b[22:0]};
            ea=(a[30:23]==0) ? -126 : int'({1'b0,a[30:23]})-127;
            eb=(b[30:23]==0) ? -126 : int'({1'b0,b[30:23]})-127;
            if(ea>eb || (ea==eb && sa>=sb)) begin
                big={1'b0,sa,3'b0};smaller=sg_shr_jam28({1'b0,sb,3'b0},ea-eb);
                exponent=ea;sign_big=a[31];sign_small=b[31];
            end else begin
                big={1'b0,sb,3'b0};smaller=sg_shr_jam28({1'b0,sa,3'b0},eb-ea);
                exponent=eb;sign_big=b[31];sign_small=a[31];
            end
            if(sign_big==sign_small) value=big+smaller;else value=big-smaller;
            sign_out=(value==0) ? (a[31]&b[31]) : sign_big;
            sg_add=sg_pack48(sign_out,{20'b0,value},exponent-26);
        end
    endfunction

    function automatic [32:0] sg_mul(input logic [31:0] a,b);
        logic [23:0] sa,sb;
        logic [47:0] product;
        integer ea,eb;
        begin
            sa={|a[30:23],a[22:0]};sb={|b[30:23],b[22:0]};
            ea=(a[30:23]==0) ? -126 : int'({1'b0,a[30:23]})-127;
            eb=(b[30:23]==0) ? -126 : int'({1'b0,b[30:23]})-127;
            product=sa*sb;
            sg_mul=sg_pack48(a[31]^b[31],product,ea+eb-46);
        end
    endfunction

    function automatic [31:0] sg_order(input logic [31:0] f);
        logic [31:0] z;
        begin z=(f[30:0]==0)?32'b0:f;sg_order=z[31]?~z:(z^32'h80000000);end
    endfunction
    function automatic logic sg_worse(input logic [31:0] ascore,aindex,bscore,bindex);
        begin sg_worse=(sg_order(ascore)<sg_order(bscore)) ||
            ((sg_order(ascore)==sg_order(bscore)) && aindex>bindex);end
    endfunction
endpackage
