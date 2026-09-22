# SparseGate 算术核心接口 v1

模块 `sg_index_core`，默认 `MAX_HEADS=32, TOPK_MAX=512, LANES=16`。固定 D=128、group=32，LANES 必须整除32。同步上升沿、低有效异步复位。所有 valid/ready 握手在上升沿生效；输出在背压期间不变。

| 信号 | 方向/位宽 | 含义 |
|---|---|---|
| q_we / q_ready | 入/出1 | 装载一个Q字节；仅活动job且尚未成功计算key时允许 |
| q_head / q_offset / q_data | 入6/7/8 | head=0..31；offset0..63为packed FP4（低nibble先），64..67是4个E8M0 scale，68..69是signed BF16 weight小端 |
| q_load_error | 出1 | 当拍握手地址非法；不写入 |
| key_we / key_ready | 入/出1 | 装载一个K字节；仅活动job等候key时允许 |
| key_offset / key_data | 入7/8 | offset0..63 packed FP4，64..67 E8M0 scale |
| key_load_error | 出1 | 当拍握手地址非法；不写入 |
| job_valid / job_ready | 入/出1 | 开始job，清空选择堆和Q有效位 |
| cfg_heads / cfg_k | 入6/10 | 1..MAX_HEADS / 1..TOPK_MAX |
| key_valid / key_accept | 入/出1 | 触发当前完整K记录计算；key字节有效位在此握手后清空 |
| key_index | 入32 | 全局token index；调用方保证一次scan内无重复index |
| score_valid / score_ready | 出/入1 | 当前key已计算并完成堆更新 |
| score_index / score_value / score_error | 出32/32/8 | index，FP32 score，错误码；错误时score值不作为有效分数 |
| finish_valid / finish_ready | 入/出1 | 明确结束scan；此前score握手均已完成 |
| result_valid / result_ready | 出/入1 | 选中结果流，数量min(K,成功key数) |
| result_index / result_score / result_last | 出32/32/1 | 堆中选中集合，输出顺序不保证；最后一项last=1 |
| done_valid / done_ready / error_code | 出/入/出1/1/8 | job完成；错误job不输出任何选择结果 |
| busy | 出1 | 活动job或等待done消费 |
| cycles / keys_scored / mac_terms | 出64/32/64 | job内部真实周期、成功数值打分key数、实际执行FP4乘积项数 |

外部96B记录格式由wrapper管理；core只消费上述有效70B Q / 68B K，不处理padding或地址。原始FP4/scale数据真实进入核心计算；软件不得只给预计算score。

典型顺序：job握手 → 装Q → 等key_ready → 装68B K → key握手 → score握手 → 下一K → finish握手 → 消费结果集合 → done握手。job开始握手后的下一拍允许装Q；key_valid/finish_valid与Q或K写同时出现时优先装载；finish与key_valid同时出现时优先key。Q完整性在key开始时逐head核查；K每次触发必须装满68B。复位清除Q/K有效位及整个job，不保留驻留。epoch、跨层复用、候选合法性由wrapper管理，core不冒充实现这些控制。

数值合同：E2M1正半区对应 `0,.5,1,1.5,2,3,4,6`，bit3为符号，±0等价。将值乘2后用小整数精确乘加，32维group结果在[-4608,4608]。group转换为FP32：`dot_int * 2^(q_scale+k_scale-256)`，RNE、保留subnormal。4group从g0到g3以FP32 RNE加法累加，完整head完成后ReLU，再乘signed BF16 weight（精确扩展FP32），从h0到h(H−1)逐头FP32 RNE加。TopK按score降序、同分index升序，±0同分。输出集合本身不排序；wrapper/软件若需position排序，应在输出后明确执行。

E8M0的0..254为合法指数，255非法；weight exponent255非法。所有有限输入导致的FP32中间溢出均终止job并报告error，不生成假正常TopK；下溢不是错误。错误码：1配置，2缺Q，3缺K，4非法scale，5非有限weight，6浮点溢出。错误core必须复位或消费done后重新开始job；重新job开始时清Q有效位，需调用方重新装载全部有效记录。

实现用容量可配的minheap（根为当前最差候选），每轮比较至多两个子节点，插入/替换O(logK)，不例化512路插入比较阵列。实际综合可能将Q/heap数组映射为寄存器；没有物理SRAM绑定之前不声称SRAM宏PPA。
