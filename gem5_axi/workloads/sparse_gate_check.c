#include "sparse_gate_client.h"
static long call3(long n,long a,long b,long c){long r;__asm__ volatile("syscall":"=a"(r):"a"(n),"D"(a),"S"(b),"d"(c):"rcx","r11","memory");return r;}
static void emit(const char *s){unsigned n=0;while(s[n])++n;call3(1,1,(long)s,n);}
static void number(uint32_t value){char buf[11];unsigned n=0;do{buf[n++]=(char)('0'+value%10);value/=10;}while(value);for(unsigned i=0;i<n/2;++i){char c=buf[i];buf[i]=buf[n-1-i];buf[n-1-i]=c;}call3(1,1,(long)buf,n);}
void _start(void) {
    SgReport r={0};int code=sg_acceptance(&r);
    if(code){emit("CPU SPARSE GATE FAIL stage=");number((uint32_t)code);emit("\n");}
    else {
        for(unsigned i=0;i<5;++i){SgCommandReport *c=&r.commands[i];
            emit("GATE_COMMAND mode=");number(c->mode);emit(" status=");number(c->status);
            emit(" count=");number(c->count);emit(" scores=");number(c->scores);
            emit(" read_beats=");number(c->read_beats);emit(" write_beats=");number(c->write_beats);
            emit(" cycles=");number(c->cycles);emit("\n");}
        emit("CPU SPARSE GATE PASS heads=");number(SG_HEADS);emit(" keys=");number(SG_NKEYS);
        emit(" topk=");number(SG_TOPK);emit(" commands=5 errors_expected=1 gather_bytes=288\n");
    }
    call3(60,code,0,0);__builtin_unreachable();
}
