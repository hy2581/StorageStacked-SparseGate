"""Minimal gem5 SE host needed to configure Vortex CP DMA.

The host CPU runs the Vortex runtime; gate MMIO and data traffic are issued by
Vortex CP DMA through its BAR, not by this host CPU.
"""

from m5.objects import (AddrRange, Cache, L2XBar, Process, SimpleMemory,
                        SrcClockDomain, TimingSimpleCPU, VoltageDomain)

HOST_HEAP = (0x80000000, 0x10000000)
VORTEX_CP = (0x20000000, 0x200)
VORTEX_BAR = (0x100000000, 0x100000000)
HOST_CLOCK = "2GHz"
VORTEX_CLOCK = "1GHz"


class L1Cache(Cache):
    assoc = 8
    tag_latency = 1
    data_latency = 1
    response_latency = 1
    mshrs = 16
    tgts_per_mshr = 20


class L1ICache(L1Cache):
    size = "32KiB"
    is_read_only = True
    writeback_clean = True


class L1DCache(L1Cache):
    size = "32KiB"


class L2Cache(Cache):
    size = "1MiB"
    assoc = 16
    tag_latency = 10
    data_latency = 10
    response_latency = 10
    mshrs = 32
    tgts_per_mshr = 12
    write_buffers = 16


def build_host(system, process, count=4):
    # The Vortex runtime uses clone(), so SE needs spare host contexts.
    system.cpu = [TimingSimpleCPU(cpu_id=i) for i in range(count)]
    system.multi_thread = count > 1
    system.l2bus = L2XBar()
    for cpu in system.cpu:
        cpu.icache = L1ICache()
        cpu.dcache = L1DCache()
        cpu.icache.cpu_side = cpu.icache_port
        cpu.dcache.cpu_side = cpu.dcache_port
        cpu.icache.mem_side = system.l2bus.cpu_side_ports
        cpu.dcache.mem_side = system.l2bus.cpu_side_ports
        cpu.createInterruptController()
        cpu.interrupts[0].pio = system.membus.mem_side_ports
        cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
        cpu.interrupts[0].int_responder = system.membus.mem_side_ports
        cpu.workload = process
        cpu.createThreads()
    system.l2cache = L2Cache()
    system.l2cache.cpu_side = system.l2bus.mem_side_ports
    system.l2cache.mem_side = system.membus.cpu_side_ports


def build_vortex(system, library):
    from m5.objects import VortexGPGPU

    system.vortex = VortexGPGPU(
        library=library, kernel="", pio_addr=VORTEX_CP[0],
        pio_size=VORTEX_CP[1], pin_addr=VORTEX_BAR[0],
        pin_size=VORTEX_BAR[1],
        clk_domain=SrcClockDomain(
            clock=VORTEX_CLOCK, voltage_domain=system.clk_domain.voltage_domain),
        timing_memory=True, exit_on_first_pio=False, trace_enable=False,
        trace_addr_offset=VORTEX_BAR[0],
    )
    system.vortex.pio = system.membus.mem_side_ports
    system.vortex.dma = system.membus.cpu_side_ports


def map_vortex_windows(process):
    # The host runtime has fixed CP and BAR addresses; keep both uncacheable.
    process.map(VORTEX_CP[0], VORTEX_CP[0], 0x1000, cacheable=False)
    process.map(VORTEX_BAR[0], VORTEX_BAR[0], VORTEX_BAR[1], cacheable=False)
