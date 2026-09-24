# 构建与运行

在 Linux x86-64 上使用带子模块的仓库检出。项目固定外部 gem5、Vortex 源码版本，
需要 Python、C/C++ 编译器、CMake、Ninja、Verilator、make、XeLaTeX、BibTeX 与 Poppler。
环境脚本准备项目专用工具链，默认写入 `$HOME/.local/share/storagestacked-unified`；
可通过 `SS_DEPS_ROOT` 改变路径。运行仿真前确认构建目录有足够空间。

```sh
git submodule update --init --recursive
bash env/bootstrap_vortex.sh
bash env/build_vortex.sh
bash env/build_sparse_gate.sh
bash env/run_vortex_gate.sh results/vortex-gate-cp-new
bash env/run_vortex_gate.sh results/vortex-gate-long-new long
bash paper/build.sh
```

每次运行使用新的结果目录。`run_vortex_gate.sh` 会检查 Vortex 源轨迹、AXI/UCIe
链路、RTL 状态、DMA 读写拍数及聚集输出。默认配置是 H4/N16/K4 FULL 冒烟用例；
`long` 使用固定的 H32/N640/K512 输入，含预训练索引头权重、合成激活及字节图案 KV。
长配置会生成数 GB 的轨迹，分析时间也明显增加。
