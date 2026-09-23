# StorageStacked-SparseGate 工作约定

- 本仓库仅维护 Vortex CP DMA 发起的 SparseGate 在线路径。gem5 的 SE 宿主 CPU 只运行 Vortex 软件；门控 MMIO 与数据请求由 Vortex CP DMA 发出。
- 外部子模块仅有 `gem5` 与 `vortex-gpu/vortex`，版本见 `env/sources.lock.json`。不要重置其本地适配，也不要向 `fmq03/StorageStacked` 推送。
- 内部 `gem5_axi`、`gem5_new`、`axi2flit`、`ucie-model`、`mem_sim` 是普通源码目录。
- 保持 AXI256 数据宽度、AXI2Flit/UCIe 请求与返回、同一个在线 mem_sim 镜像和 gem5/SystemC 单时间轴。
- 构建入口依次为 `env/bootstrap_vortex.sh`、`env/build_vortex.sh`、`env/build_sparse_gate.sh`；运行入口为 `env/run_vortex_gate.sh`。
- 论文只维护 `paper/SparseGate-final.pdf` 与其中文 LaTeX 源码。系统结果不得把独立核心实验或已移除的 CPU/NPU 用例算作 Vortex 在线系统测量。
- 交付核对使用源码提交号或版本、文件名和大小、实际构建与运行结果；不生成文件摘要清单。
