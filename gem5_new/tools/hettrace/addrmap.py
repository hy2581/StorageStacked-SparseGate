"""Address and source identities for Vortex CP DMA traces."""

MAP_ADDR_BITS = 64
TICKS_PER_SECOND = 1000000000000
SOURCES = {
    'host': (0, 'post_llc', 2000, 500),
    'vortex': (1, 'post_llc', 1000, 1000),
}
SRC_NAME_BY_ID = {item[0]: name for name, item in SOURCES.items()}
REGIONS = {
    'vortex_cp': (0x20000000, 0x200, 'mmio', ('host',)),
    'host_heap': (0x80000000, 0x10000000, 'local', ('host',)),
    'vortex_bar': (0x100000000, 0x100000000, 'bar', ('host', 'vortex')),
}
HANDOFF_REGIONS = ('vortex_bar',)


def region_of(addr):
    for name, (base, size, _kind, _accessors) in REGIONS.items():
        if base <= addr < base + size:
            return name
    return None


def is_traced(addr):
    base, size, _, _ = REGIONS['vortex_bar']
    return base <= addr < base + size


def may_access(source, addr):
    name = region_of(addr)
    return name is not None and source in REGIONS[name][3]
