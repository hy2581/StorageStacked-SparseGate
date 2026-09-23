#!/usr/bin/env python3
"""Generate Chinese numerical text from the evidence of the finalized English paper.

This script neither runs the English generator nor changes evidence or figures.
It writes five .tex files and prints a JSON provenance receipt to stdout.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "paper/zh/generated"
ENGLISH_MANIFEST = "paper/generated/manifest.json"
CHECKED_INPUTS = {}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    item = ROOT / path
    CHECKED_INPUTS[str(item.relative_to(ROOT))] = sha(item)
    return json.loads(item.read_text(encoding="utf-8"))


def verify_file(path, digest):
    item = ROOT / path
    require(item.is_file(), "Missing locked file: " + str(path))
    require(sha(item) == digest, "Changed locked file: " + str(path))
    CHECKED_INPUTS[str(item.relative_to(ROOT))] = digest


def check_sources(value):
    if isinstance(value, dict):
        for key in ("source_sha256", "rtl_model_source_sha256"):
            for path, digest in value.get(key, {}).items():
                verify_file(path, digest)
        for child in value.values():
            check_sources(child)
    elif isinstance(value, list):
        for child in value:
            check_sources(child)


def table(name, caption, columns, header, rows):
    text = ("\\begin{table}[t]\n\\centering\\caption{" + caption
            + "}\n\\label{tab:" + name + "}\n\\small\n\\begin{tabular}{"
            + columns + "}\\toprule\n")
    text += " & ".join(header) + r"\\\midrule" + "\n"
    text += "\n".join(" & ".join(map(str, row)) + r"\\" for row in rows)
    return text + "\n\\bottomrule\\end{tabular}\n\\end{table}\n"


def validate_inputs():
    manifest = read(ENGLISH_MANIFEST)
    require(manifest["schema"] == "paper_generation_v1", "Unexpected English manifest schema")
    require(manifest["preview"] is False and not manifest["missing_evidence"],
            "English paper must be finalized with complete evidence")
    verify_file("paper/prepare.py", manifest["generator_sha256"])
    for group in ("input_sha256", "outputs"):
        for path, digest in manifest[group].items():
            verify_file(path, digest)
    evidence = {path: read(path) for path in manifest["input_sha256"]}
    for value in evidence.values():
        check_sources(value)
    for path, value in evidence.items():
        require(value.get("passed", value.get("status") == "PASS") is True,
                "Evidence is not accepted: " + path)
    require(evidence["evidence/core/validation.json"]["float"]["passed"],
            "Floating-point regression incomplete")
    system = evidence["evidence/system/summary.json"]
    require(system["status"] == "PASS" and not system["failures"], "System acceptance incomplete")
    verify_file(system["source_lock"]["path"], system["source_lock"]["sha256"])
    verify_file("env/collect_sparse_gate_system.py", system["collector_sha256"])
    return manifest, evidence


def generate():
    manifest, evidence = validate_inputs()
    core = evidence["evidence/core/validation.json"]
    lane = evidence["evidence/core/lane_sweep.json"]
    research = evidence["evidence/research/summary.json"]
    system = evidence["evidence/system/summary.json"]
    completion = evidence["evidence/system/completion_window.json"]
    synthesis = evidence["evidence/core/synthesis.json"]
    area = evidence["evidence/core/area_units.json"]

    counts = {"CoreCaseCount": core["case_count"], "CoreKeyCount": core["successful_keys"],
              "CoreMacCount": core["mac_terms"], "FpCaseCount": core["float"]["total"],
              "TensorBytes": research["tensor_payload_bytes"],
              "OraclePairCount": research["arithmetic_audit"]["add_checked"],
              "RationalCaseCount": research["arithmetic_audit"]["rational_round_checked"]}
    learned = next(c for c in research["fixture_cases"]
                   if c["name"] == "pretrained-layer20-random-activation-top512")["torch_comparison"]
    tied = next(c for c in research["fixture_cases"] if c["name"] == "zero-ties-top512")["torch_comparison"]
    require(learned["fp32"]["max_abs_error"] == 0 and
            learned["bf16_demo"]["topk_symmetric_difference"] == 0,
            "Published reference comparison changed")
    counts["TieDifference"] = tied["fp32"]["topk_symmetric_difference"]
    macros = {key: format(value, ",") for key, value in counts.items()}
    macros.update(BfRelative=format(learned["bf16_demo"]["relative_l2_error"], ".6g"),
                  BfAbsolute=format(learned["bf16_demo"]["max_abs_error"], ".6g"))
    outputs = {"results.tex": "\n".join("\\newcommand{\\" + key + "}{" + value + "}"
                                       for key, value in macros.items()) + "\n"}
    require(outputs["results.tex"] == (ROOT / "paper/generated/results.tex").read_text(),
            "Chinese and English numerical macros differ")

    wanted = {"random_h32_n521_k512": "随机完整配置", "all_equal_shuffled_ids": "同分索引乱序",
              "negative_head_weights": "有符号头权重", "subnormal_scores": "次正规数得分",
              "candidate_subset": "候选子集"}
    rows = []
    for case in core["cases"]:
        if case["name"] in wanted:
            label = wanted[case["name"]]
            if case["submitted"] < case["positions"]:
                label += f"（C={case['submitted']}）"
        elif "pretrained-layer20" in case["name"]:
            label = "权重：" + (f"C={case['submitted']}" if "reindex" in case["name"]
                               else "小例全扫描" if "small" in case["name"] else "Top-512")
        else:
            continue
        require(case["expected_error"] == case["measured"]["error"] == 0,
                "Selected core case is not successful")
        rows.append([label, case["heads"], case["positions"], case["topk"],
                     f"{case['measured']['cycles']:,}", "通过"])
    require(len(rows) == 8, "Unexpected published core-case set")
    outputs["core_table.tex"] = table(
        "core", "部分核心验证用例。C 表示仅扫描 N 个位置中的部分位置时提交的候选数。"
        "周期数包含规定的逐字节装载接口和测试背压，不能视为系统延迟。",
        "lrrrrl", ["用例", "H", "N", "K", "周期数", "检查"], rows)

    cases = system["cases"]
    names = ["baseline_cpu", "baseline_xpu", "cpu_synthetic", "cpu_real_weights",
             "three_source_coexistence", "cpu_top512"]
    require(all(cases[name]["passed"] and cases[name]["status"] == "PASS" for name in names),
            "Required native case incomplete")
    cpu, xpu = cases["baseline_cpu"], cases["baseline_xpu"]
    feedback, adapter, controls = (system[k] for k in ("gate_memory_feedback", "adapter_contract", "wave_controls"))
    require(feedback["passed"] and adapter["passed"] and controls["passed"], "System control checks incomplete")
    require(len(controls["negative_controls"]) == 3 and
            all(c["detected"] for c in controls["negative_controls"]), "Trace corruption controls incomplete")
    require(completion["command"] == cases["cpu_synthetic"]["commands"][0]["rtl_interval"],
            "Completion figure does not correspond to accepted native command")
    completion_gap = (completion["command"]["end_tick_fs"] - completion["command"]["last_b_tick_fs"])
    require(completion_gap == 3 * completion["axi_period_fs"], "Published completion ordering changed")
    sys_text = (
        f"原统一链路通过 {cpu['native_tests_passed']} 项原生测试、{len(cpu['cases'])} 组 CPU／测试器用例和 "
        f"{len(xpu['cases'])} 组 XPU 用例。此后，SparseGate 分别通过合成输入 CPU 程序、预训练权重派生输入 "
        "CPU 程序及三处理源共存程序的验证。共存程序先执行原有 GPU／NPU 工作负载，再发出门控命令；"
        "该结果证明新增电路可与原处理源在保留的链路上共存，不代表门控与 GPU／NPU 同时争用资源。\n\n"
        "每次门控运行均依据独立参考结果，逐项核对全部返回的得分／索引记录及聚集输出的每一个字节。"
        "小规模用例依次覆盖 FULL、有效 REUSE、REINDEX、过期 epoch 拒绝和 FULL 恢复。"
        "过期命令不产生被接受的 DMA 传输。验证交叉核对原生 AXI 波形、UCIe Flit、后端事件和存储命令，"
        "并保留可执行文件与源代码的摘要。每条命令的计数器均与 RTL 忙区间独立比对，成功 DONE 还须晚于"
        "最后一次 DMA 写响应。另设适配层与 RTL 联合测试，验证不支持的独占访问被拒绝，以及普通访问能够恢复。\n\n"
        "波形检查器还识别出对已记录轨迹施加的三种受控错误：周期计数加一、DMA 读计数加一，"
        "以及在最后一次 B 通道握手时提前置位 DONE。上述错误仅通过检查时的数据覆盖注入，不修改原始仿真文件。\n\n"
    )
    sys_text += r"""\begin{figure*}[t]
\centering\includegraphics[width=.94\textwidth]{completion_wave.pdf}
\caption{H4/N16/K4 CPU 程序中，首次成功 FULL 命令完成前后的实际原生 RTL VCD 采样。电平在模型求值后记录，握手判定采用上升沿之前稳定的信号值。DONE 在最后一次 B 通道握手后的第三个 AXI 周期提交。RTL STATUS 响应与其随后沿返回协议链路的交付记录独立关联。该图为仿真波形，并非芯片实测波形。}
\label{fig:completion}
\end{figure*}
"""
    case, slow = cases["cpu_real_weights"], feedback["slow_case"]
    cmds, slow_cmds = case["commands"][:3], slow["commands"][:3]
    require(slow["passed"] and [c["mode"] for c in cmds] == [c["mode"] for c in slow_cmds]
            == ["FULL", "REUSE", "REINDEX"], "Memory-feedback command sequence changed")
    require(slow["memsim_period_fs"] == 4 * case["memsim_period_fs"] and
            slow["axi_period_fs"] == case["axi_period_fs"], "Memory-feedback clocks changed")
    for key in ("guest_binary_sha256", "rtl_model_source_sha256", "model_library_sha256"):
        require(slow[key] == case[key], "Memory-feedback implementation differs: " + key)
    for a, b in zip(cmds, slow_cmds):
        require(a["result_count"] == b["result_count"] == 8 and b["cycles"] > a["cycles"],
                "Memory-feedback result count or latency relationship changed")
        for key in ("dma_read_beats", "dma_write_beats", "dma_read_bytes", "dma_write_bytes", "score_count"):
            require(a[key] == b[key], "Memory-feedback DMA or score count changed")
    require(cmds[2]["rtl_interval"]["ncand"] == 16 and cmds[0]["rtl_interval"]["heads"] == 32
            and cmds[0]["rtl_interval"]["nkeys"] == 64, "Published small-case shape changed")
    rows = [[a["mode"], a["score_count"], a["dma_read_beats"], a["dma_write_beats"],
             f"{a['cycles']:,}", f"{b['cycles']:,}"] for a, b in zip(cmds, slow_cmds)]
    sys_text += table("modes", "预训练权重派生 H32/N64/K8 程序的实测 RTL 命令计数。REINDEX 包含 16 个候选。"
                      "R／W 为 DMA 读／写数据拍数，在两种存储周期下保持一致；每个选中索引对应搬运 288 B KV 数据。", "lrrrrr",
                      ["模式", "评分条目数", "R", "W", r"$1\times$ 周期", r"$4\times$ 周期"], rows)
    sys_text += (
        f"AXI 仿真周期为 {case['axi_period_fs']/1e6:g} ns。命令周期数计量 RTL 从开始忙碌到接收最后写响应并提交完成状态的区间，"
        "主机程序的运行时间则还包含协议传输与软件交互。上述输入下的三条成功命令均返回八条结果记录。\n\n"
        f"将在线存储周期由 {case['memsim_period_fs']/1e6:g} ns 增大至 {slow['memsim_period_fs']/1e6:g} ns 后，"
        "被测可执行文件、RTL、得分和 DMA 数量均保持不变，所有成功命令的周期数均增加，"
        f"完整主机程序结束时间增加 {feedback['host_finish_delta_fs']/1e9:.3f} $\\mu$s。"
        "轮询请求数量可以随等待时间变化，因此该实验用于确认在线存储延迟能够反馈到电路及主机执行过程，"
        "不能解释为固定指令工作量下的加速比比较。\n\n"
    )
    full, reuse = cases["cpu_top512"]["commands"]
    require([full["mode"], reuse["mode"]] == ["FULL", "REUSE"] and
            full["result_count"] == reuse["result_count"] == 512 and
            full["rtl_interval"]["heads"] == 32 and full["rtl_interval"]["nkeys"] == 640,
            "Published full-shape native case changed")
    gathered_bytes = reuse["dma_read_bytes"]
    require(gathered_bytes == full["result_count"] * 288 and
            full["dma_write_bytes"] == reuse["dma_write_bytes"] == gathered_bytes + 512 * 32,
            "Full-shape gather and result payload do not match")
    sys_text += (
        "另设完整配置 H32/N640/K512 程序，先后执行 FULL 和 REUSE，并使用彼此独立的目标地址。"
        f"每条命令均核对全部 512 条得分／索引记录、填充字节及 {gathered_bytes:,} B 聚集数据。"
        f"FULL 需要 {full['cycles']:,} 个忙周期，产生 {full['dma_read_beats']:,} 个读数据拍和 "
        f"{full['dma_write_beats']:,} 个写数据拍；REUSE 需要 {reuse['cycles']:,} 个周期，"
        f"读／写数据拍数分别为 {reuse['dma_read_beats']:,}／{reuse['dma_write_beats']:,}。"
        "该用例将完整配置的选择验证扩展至实际在线链路；小规模 REINDEX 与错误恢复序列由另一组用例覆盖。\n\n"
    )
    sys_text += r"""\begin{figure*}[t]
\centering\includegraphics[width=.86\textwidth]{native_modes.pdf}
\caption{两种在线存储周期下 H32/N64/K8 命令的实测延迟，以及两种周期下相同的 DMA 有效载荷。REUSE 保留已有选择，REINDEX 对外部提供的候选子集重新算分；两者工作内容不同，不能作为可互换的精度基线。有效载荷包含结果记录与聚集 KV 数据的写回，不含主机上传、MMIO、回读及链路封装开销。}
\label{fig:native}
\end{figure*}
"""
    outputs["system_results.tex"] = sys_text

    runs = lane["results"]
    require([r["lanes"] for r in runs] == [8, 16, 32] and all(r["passed"] for r in runs),
            "Lane-sweep configuration or status changed")
    for key in ("fixture_sha256", "command_sha256", "selected_sha256", "selected_count"):
        require(len({r[key] for r in runs}) == 1, "Lane sweep is not matched: " + key)
    require(all(r["measured"]["mac_terms"] == runs[0]["measured"]["mac_terms"] for r in runs),
            "Lane-sweep arithmetic counts differ")
    a, b, c = [r["measured"]["cycles"] for r in runs]
    impl = r"""\begin{figure}[t]
\centering\includegraphics[width=\columnwidth]{lane_sweep.pdf}
\caption{同一预训练权重派生 H32/N640/K512 输入下，运算通道数对核心周期数的影响。全部得分和选择结果一致。该核心独立测试不包含封装层的位置排序及原生 DMA／存储等待；结果输出周期取决于测试平台的 ready 序列。不同实现之间不预设时钟频率或 PPA 等价。}
\label{fig:lanes}
\end{figure}
"""
    impl += (
        f"在相同输入及相同握手调度下，8／16／32 路实现分别需要 {a:,}、{b:,} 和 {c:,} 个周期。"
        f"各实现均计算 {runs[0]['measured']['mac_terms']:,} 个乘积项，并选择相同的 {runs[0]['selected_count']} 个索引。"
        f"从 8 路增加至 16 路、从 16 路增加至 32 路时，优化前后周期数之比分别为 {a/b:.3f}$\\times$ 和 {b/c:.3f}$\\times$。"
        "增加运算通道可缩短整数乘积的分批计算时间，但缩放转换与 FP32 归约仍串行执行。"
        "装载、选择和结果输出的开销也未消除，因此该结果不意味着性能线性扩展，亦不意味着不同实现具有相同的可达频率。\n\n"
    )
    full_core = next(v for v in core["cases"] if v["name"] == "external:pretrained-layer20-random-activation-top512.json")
    impl += (
        f"表~\\ref{{tab:core}} 中 Top-512 用例的 {full_core['measured']['cycles']:,} 个周期来自另一组随机背压序列，"
        f"与受控通道数实验中 16 路实现的 {b:,} 个周期不属于完全相同的时序实验。\n\n"
    )

    d, coverage, clock = synthesis, synthesis["timing_coverage"], synthesis["clock_model"]
    require(all(d[k] for k in ("passed", "completed", "mapped", "mapping_passed", "timing_passed", "design_rules_passed"))
            and d["unmapped_leaf_references"] == 0, "Synthesis acceptance incomplete")
    require(coverage["status"] == "PASS" and coverage["passed"] and coverage["io_delay_check"]["passed"]
            and coverage["reset_false_path_verified"] and coverage["unwaived_warning_count"] == 0,
            "Timing-constraint coverage incomplete")
    require(d["setup_slack_ns"] >= 0 and d["hold_slack_ns"] >= 0 and
            d["design_rule_violation_count"] == sum(d["design_rule_violation_counts"].values()) == 0,
            "Mapped timing or electrical checks changed")
    require(area["status"] == "VERIFIED" and area["liberty_area_unit_verified"] and area["area_unit"] == "um2"
            and area["kit_compatibility"]["passed"] and area["lef_reference"]["definition_checked"],
            "Area-unit evidence incomplete")
    require(area["dc_database_sha256"] == d["library"]["sha256"] and
            area["inputs"]["dc_cell_areas"]["sha256"] == d["library_cell_areas"]["sha256"],
            "Area evidence refers to a different DC database or readback")
    for key in ("liberty_lef_match", "dc_cell_area_match"):
        match = area[key]
        require(match["passed"] and match["compared"] == match["exact_matches"] == d["library_cell_areas"]["rows"]
                and match["mismatches"] == 0, "Cell-area comparison is not exact: " + key)
    require(clock["ideal_clock"] and clock["cts_status"] == "NOT_RUN"
            and clock["physical_clock_tree_status"] == "NOT_IMPLEMENTED"
            and clock["extracted_parasitics_status"] == "NOT_RUN"
            and not d["physical_signoff"] and d["gate_level_equivalence_status"] == "NOT_RUN",
            "Published physical-implementation scope changed")
    clock_net = next(net for net in clock["high_fanout_nets"] if net["name"] == clock["source"])
    impl += table("synthesis", "16 路评分／堆核心在 TSMC 28 nm HPC+ 标准单元库下使用 Design Compiler 获得的实际综合映射结果。"
                  "数组由触发器实现；未完成布局布线、寄生互连提取、门级等价验证或物理签核。", "lr",
                  ["指标", "测量值／配置值"], [
                      ["库工艺角", r"TT 0.9 V 25 $^{\circ}$C"],
                      ["目标周期（ns）", f"{d['target_period_ns']:.3f}"],
                      [r"映射单元面积（$\mu$m$^2$）", f"{d['cell_area_library_units']:,.2f}"],
                      ["叶单元数", f"{d['leaf_cells']:,}"], ["时序单元数", f"{d['registers']:,}"],
                      ["建立时间裕量（ns）", f"{d['setup_slack_ns']:+.6f}"],
                      ["保持时间裕量（ns）", f"{d['hold_slack_ns']:+.6f}"],
                      ["电气约束违例条目数", d["design_rule_violation_count"]], ["约束覆盖检查", "通过"]])
    require(d["library_corner"] == "TT 0.9V 25C", "Published library corner changed")
    comb, noncomb, total = (d[k] for k in ("combinational_cell_area_library_units",
                                         "noncombinational_cell_area_library_units", "cell_area_library_units"))
    require(total > 0 and 0 <= comb <= total and 0 <= noncomb <= total, "Invalid cell-area decomposition")
    impl += (
        "在上述映射核心模型中，报告的建立时间与保持时间检查均满足所给约束。"
        f"但建立时间裕量仅为 {d['setup_slack_ns']*1e6:g} fs，保持时间裕量为 {d['hold_slack_ns']*1e3:g} ps；"
        "接近零的名义建立时间裕量不足以证明物理实现具有稳健的工作频率。"
        "电气约束违例条目统计转换时间、电容、扇出及其他报告的电气限制，同一对象若出现在不同类别中则分别计数。"
        "该检查既不同于建立／保持时间检查，也不同于版图 DRC。独立的时钟与 I/O 约束覆盖检查通过，"
        "其中复位信号按文档规定设为假路径。"
        f"组合单元面积为 {comb:,.2f} $\\mu$m$^2$，非组合单元面积为 {noncomb:,.2f} $\\mu$m$^2$，"
        f"占总面积的 {100*noncomb/total:.1f}\\%。后者同时包含控制状态与触发器存储，不能单独归因于 Q 或堆存储。"
        f"全部 {area['liberty_lef_match']['compared']:,} 个 Liberty 单元的面积均与同名 LEF 单元的宽高乘积精确一致，"
        "工艺库发布版本的兼容关系亦已核对；实际 DC 数据库中的单元面积也逐项精确匹配。"
        "LEF SIZE 的尺寸单位为微米~\\cite{lefdef}，因此这里得到的是标准单元占用面积，而非布局后的核心面积或芯片面积。"
        "综合对象不包含 AXI 封装层、DMA、处理器模型及 UCIe 系统。"
        "综合使用理想时钟，未建模 CTS 与实际时钟网络负载；"
        f"对于报告含 {clock_net['loads']:,} 个负载的时钟网，工具采用 {clock['assumed_fanout_for_delay']:,} 的扇出估计值。"
        "独立的已保存设计回读核查了映射与时序报告，但这不构成等价性证明。"
        "仿真时钟仅为测试设置，不代表已经实现的芯片工作频率。\n"
    )
    outputs["implementation_results.tex"] = impl
    outputs["abstract_results.tex"] = (
        f"在原生 H32/N640/K512 在线用例中，FULL 与 REUSE 分别需要 {full['cycles']:,} 和 {reuse['cycles']:,} 个忙周期，"
        f"每条命令均逐项验证全部选择记录及 {gathered_bytes:,} B 聚集数据。"
        f"16 路核心在 28 nm HPC+ 标准单元库 TT、0.9 V、25 $^{{\\circ}}$C 条件下的映射面积为 "
        f"{d['cell_area_library_units']/1e6:.3f} mm$^2$。在理想时钟模型下满足名义 {d['target_period_ns']:g} ns "
        f"时序目标，但报告的建立时间裕量仅为 {d['setup_slack_ns']*1e6:g} fs。\n"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        (OUT / name).write_text(content, encoding="utf-8")
    receipt = {"schema": "chinese_paper_results_v1", "passed": True,
               "english_manifest": {"path": ENGLISH_MANIFEST, "sha256": sha(ROOT / ENGLISH_MANIFEST)},
               "input_sha256": dict(sorted(CHECKED_INPUTS.items())),
               "english_output_sha256": manifest["outputs"],
               "english_generator_sha256": manifest["generator_sha256"],
               "generator_sha256": sha(__file__),
               "outputs": {str((OUT / name).relative_to(ROOT)): sha(OUT / name) for name in outputs},
               "scope": "Chinese numerical prose and tables only; accepted evidence reused without rerunning experiments."}
    return receipt


if __name__ == "__main__":
    print(json.dumps(generate(), ensure_ascii=False, indent=2))
