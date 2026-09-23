"""Vortex CP DMA -> AXI256 -> AXI2Flit -> UCIe -> SparseGate RTL."""

import argparse
import importlib.util
import os
from pathlib import Path

import m5
from m5.objects import (AddrRange, AxiDemo, Gem5ToTlmBridge64, HetAxiMonitor,
                        Process, Root, SEWorkload, SimpleMemory, SrcClockDomain,
                        System, SystemC_Kernel, SystemXBar, VoltageDomain)

project = Path(__file__).resolve().parents[2]
helper = project / 'gem5_new/gem5int/configs/het/vortex_host.py'
spec = importlib.util.spec_from_file_location('vortex_host', helper)
front = importlib.util.module_from_spec(spec)
spec.loader.exec_module(front)

p = argparse.ArgumentParser()
p.add_argument('--cmd', required=True)
p.add_argument('--vortex-library', required=True)
p.add_argument('--vortex-host-rt-dir', required=True)
p.add_argument('--gate-library', required=True)
p.add_argument('--gate-base', type=lambda value: int(value, 0), default=0x1900f0000)
p.add_argument('--max-ticks', type=int, default=100000000000000)
a = p.parse_args()
for path in (a.cmd, a.vortex_library, a.gate_library):
    if not Path(path).is_file():
        p.error('Missing required file: ' + path)

out = Path(m5.options.outdir).resolve()
(out / 'hettrace').mkdir(parents=True, exist_ok=True)
os.environ['HETTRACE_DIR'] = str(out / 'hettrace')
os.environ['HETTRACE_FILTER'] = 'all'
os.environ['HETTRACE_FORMAT'] = 'binary'
m5.ticks.setGlobalFrequency('1fs')

system = System()
system.clk_domain = SrcClockDomain(clock=front.HOST_CLOCK,
                                   voltage_domain=VoltageDomain())
system.mem_mode = 'timing'
system.membus = SystemXBar()
system.system_port = system.membus.cpu_side_ports
host_range = AddrRange(front.HOST_HEAP[0], size=front.HOST_HEAP[1])
system.mem_ranges = [host_range]
system.host_mem = SimpleMemory(range=host_range, latency='10ns',
                               conf_table_reported=True)
system.host_mem.port = system.membus.mem_side_ports
system.axi = AxiDemo(
    backend='aou', memory_backend='memsim', base=0x90000000,
    size=0x170000000, gate_enable=True,
    gate_library=str(Path(a.gate_library).resolve()), gate_base=a.gate_base,
    memsim_channels=8, memsim_scale=1, memsim_queue=4, memsim_slots=8,
    outstanding=16, planes=2, stalls=True, replay=False, trace_dir=str(out),
)
system.bridge = Gem5ToTlmBridge64(
    addr_ranges=[AddrRange(front.VORTEX_BAR[0], size=front.VORTEX_BAR[1])])
system.bridge.tlm = system.axi.tlm
system.het_monitor = HetAxiMonitor(unique_packet_ids=True, trace_host=True,
                                   trace_vortex=True)
system.het_monitor.mem_side_port = system.bridge.gem5
system.het_monitor.cpu_side_port = system.membus.mem_side_ports
system.workload = SEWorkload.init_compatible(a.cmd)
runtime_env = ('LD_LIBRARY_PATH=' + a.vortex_host_rt_dir + ':' +
               os.environ['SS_PREFIX'] + '/lib', 'VORTEX_DRIVER=gem5-x86_64')
process = Process(pid=100, cmd=[os.path.abspath(a.cmd)],
                  executable=os.path.abspath(a.cmd), env=list(runtime_env))
front.build_host(system, process)
front.build_vortex(system, a.vortex_library)
kernel = SystemC_Kernel(system=system)
root = Root(full_system=False, systemc_kernel=kernel)
m5.instantiate()
front.map_vortex_windows(process)
event = m5.simulate(a.max_ticks)
system.axi.finish()
print('EXIT:', event.getCause(), 'code', event.getCode(), 'tick', m5.curTick())
if event.getCode() != 0 or 'exiting with last active thread context' not in event.getCause():
    raise RuntimeError('Vortex gate workload did not finish successfully')
