# Vortex 在线门控环境

外部源码仅有 gem5 与 Vortex。`sources.lock.json` 固定其提交号。
`bootstrap_vortex.sh` 准备 Linux x86-64 工具、Vortex 工具链、Ramulator 构建依赖；
`build_vortex.sh` 安装 Vortex SimX/gem5 适配并构建在线系统；
`build_sparse_gate.sh` 用 Verilator 构建高地址 Vortex BAR 对应的门控 RTL 模型；
`run_vortex_gate.sh NEW_RESULT_DIRECTORY` 编译 Vortex CP DMA 被测程序、运行仿真并核对实际轨迹。

gem5 的 SE 宿主 CPU 是 Vortex 运行时的控制环境，不作为门控 AXI 请求源。
