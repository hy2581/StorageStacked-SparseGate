#pragma once
// Standalone adapter contract test only. Production uses gem5's real curTick.
#include <systemc>
#include <cstdint>
namespace gem5 { inline uint64_t curTick(){return sc_core::sc_time_stamp().value();} }
