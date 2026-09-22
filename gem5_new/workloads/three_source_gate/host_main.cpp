/* Preserve the verified original three-source calculation, then submit the
 * same real hardware workload through this process's existing UCIe mapping. */
#define main original_three_source_main
#include "../three_source/host_main.cpp"
#undef main
#include "../../../gem5_axi/workloads/sparse_gate_client.h"
int main(int argc,char **argv) {
    int rc=original_three_source_main(argc,argv);if(rc)return rc;
    SgReport r{};rc=sg_acceptance(&r);
    if(rc){std::printf("THREE SOURCE SPARSE GATE FAIL stage=%d\n",rc);return 32+rc;}
    for(const auto& c:r.commands)
        std::printf("GATE_COMMAND mode=%u status=%u count=%u scores=%u read_beats=%u write_beats=%u cycles=%u\n",c.mode,c.status,c.count,c.scores,c.read_beats,c.write_beats,c.cycles);
    std::printf("THREE SOURCE SPARSE GATE PASS heads=%u keys=%u topk=%u commands=5 errors_expected=1 gather_bytes=288\n",SG_HEADS,SG_NKEYS,SG_TOPK);
    return 0;
}
