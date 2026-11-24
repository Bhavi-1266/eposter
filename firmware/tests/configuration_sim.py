"""Run the actual configuration C state machine with dropped packets and reboots (Linux/cc)."""
import ctypes
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
platform=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <inttypes.h>
typedef int esp_err_t,nvs_handle_t;
#define ESP_OK 0
#define ESP_ERR_NVS_NOT_FOUND 1
#define NVS_READWRITE 1
#define ESP_ERROR_CHECK(x) assert((x)==0)
#define configASSERT assert
#define ESP_LOGI(...)
#define STATUS_LED 21
#define CONFIG_IDF_TARGET_ESP32C3 1
#define MBEDTLS_MD_SHA256 1
enum {ROLE_HANDHELD=1,ROLE_STATION=2,PROFILE_ONE_BUTTON=3};
typedef struct {uint8_t magic[4],role,channel,local[6],peer[6],pmk[16],lmk[16],profile,generation[4];char id[65];} PairConfig;
typedef struct {int size,count;unsigned char bytes[32][256];} Queue;
typedef Queue* QueueHandle_t;
static int who,dropKind;
static int64_t clockMs;
static bool muted[3],setupRadio[3];
static PairConfig radio[3],factory[3];
static uint8_t nv[3][512];static size_t nvSize[3];
static char reports[3][1400];
static uint64_t randomCounter=100;
static const uint8_t publicTestKey[16]={1,2,3};
int nvs_open(const char*n,int flags,int*h){*h=who;return 0;}
int nvs_set_blob(int h,const char*k,const void*p,size_t n){assert(n<=512);memcpy(nv[h],p,n);nvSize[h]=n;return 0;}
int nvs_get_blob(int h,const char*k,void*p,size_t*n){if(!nvSize[h])return 1;assert(*n>=nvSize[h]);*n=nvSize[h];memcpy(p,nv[h],*n);return 0;}
int nvs_commit(int h){return 0;}
Queue* xQueueCreate(int count,int size){assert(count<=32 && size<=256);Queue*q=calloc(1,sizeof(Queue));q->size=size;return q;}
int xQueueSend(Queue*q,const void*p,int wait){if(q->count==32)return 0;memcpy(q->bytes[q->count++],p,q->size);return 1;}
int xQueueReceive(Queue*q,void*p,int wait){if(!q->count)return 0;memcpy(p,q->bytes[0],q->size);--q->count;memmove(q->bytes,q->bytes+1,q->count*256);return 1;}
void esp_fill_random(void*p,size_t n){uint64_t value=++randomCounter;assert(n<=8);memcpy(p,&value,n);}
void stationMessage(const char*fmt,...){va_list a;va_start(a,fmt);vsnprintf(reports[who],1400,fmt,a);va_end(a);}
void gpio_set_level(int pin,int value){}
bool channelBusy(void){return false;}
uint8_t channelCurrent(void){return radio[who].channel;}
uint8_t linkRole(void){return radio[who].role;}
uint8_t linkProfile(void){return radio[who].profile;}
void linkGetConfig(PairConfig*p){*p=radio[who];}
bool linkHasSetupKey(void){return true;}
const uint8_t*linkSetupKey(void){return publicTestKey;}
void linkHardwareAddress(uint8_t*p){memset(p,0,6);p[0]=0xa2;p[5]=who;}
int linkSwitchConfig(const PairConfig*p,bool setup){radio[who]=*p;setupRadio[who]=setup;return 0;}
int linkSetupPeer(const uint8_t*p){return 0;}
void linkForgetSetupPeer(const uint8_t*p){}
int linkSendData(const uint8_t*mac,const void*data,size_t size);
const void*mbedtls_md_info_from_type(int t){return publicTestKey;}
// Crypto itself is mbedTLS on-device; this deterministic mock exercises tag checks only.
int mbedtls_md_hmac(const void*i,const uint8_t*k,size_t kn,const uint8_t*p,size_t n,uint8_t*out){
 uint32_t h=2166136261u;for(size_t j=0;j<n;j++)h=(h^p[j])*16777619u;
 for(int j=0;j<32;j++){h=h*1664525u+1013904223u;out[j]=h>>24;}return 0;
}
'''
simulation=r'''
typedef struct {
 Journal j;Queue *rx,*rq;bool b,enter,sync,init,candidate,written;
 int m;int64_t identify,start,last,expire,saved,waitStart,waitLast;
 uint64_t nonce,waitNonce;Node discovered[MAX_NODES];int64_t seenAt[MAX_NODES];
 Request wait;uint8_t waitMac[6];
} Machine;
static Machine machines[3];
static void enterMachine(int n){
 who=n;Machine*v=&machines[n];journal=v->j;received=v->rx;requests=v->rq;storage=n;
 busy=v->b;enterSpare=v->enter;syncChannel=v->sync;initial=v->init;onCandidate=v->candidate;spareWritten=v->written;
 mode=v->m;identifyUntil=v->identify;started=v->start;lastSend=v->last;expires=v->expire;savedUntil=v->saved;
 waitStarted=v->waitStart;waitSent=v->waitLast;bootNonce=v->nonce;waitingNonce=v->waitNonce;waiting=v->wait;
 memcpy(nodes,v->discovered,sizeof(nodes));memcpy(seen,v->seenAt,sizeof(seen));memcpy(waitingMac,v->waitMac,6);
}
static void leaveMachine(void){
 Machine*v=&machines[who];v->j=journal;v->rx=received;v->rq=requests;v->b=busy;v->enter=enterSpare;v->sync=syncChannel;
 v->init=initial;v->candidate=onCandidate;v->written=spareWritten;v->m=mode;v->identify=identifyUntil;
 v->start=started;v->last=lastSend;v->expire=expires;v->saved=savedUntil;v->waitStart=waitStarted;v->waitLast=waitSent;
 v->nonce=bootNonce;v->waitNonce=waitingNonce;v->wait=waiting;
 memcpy(v->discovered,nodes,sizeof(nodes));memcpy(v->seenAt,seen,sizeof(seen));memcpy(v->waitMac,waitingMac,6);
}
int linkSendData(const uint8_t*mac,const void*data,size_t size){
 int dst=3-who;const Packet*p=data;
 if(muted[who]||muted[dst]||p->kind==dropKind)return 0;
 int sourceChannel=setupRadio[who]?11:radio[who].channel;
 int destChannel=setupRadio[dst]?11:radio[dst].channel;
 if(sourceChannel!=destChannel)return 0;
 uint8_t dest[6];if(setupRadio[dst]){memset(dest,0,6);dest[0]=0xa2;dest[5]=dst;}else memcpy(dest,radio[dst].local,6);
 if(memcmp(mac,broadcast,6)&&memcmp(mac,dest,6))return 0;
 Received item={0};assert(size==sizeof(Packet));memcpy(&item.packet,data,size);
 if(setupRadio[who])linkHardwareAddress(item.mac);else memcpy(item.mac,radio[who].local,6);
 xQueueSend(machines[dst].rx,&item,0);return 0;
}
static PairConfig makeConfig(int role,int ch,const char*name){
 PairConfig p={.magic={'R','C','F','2'},.role=role,.channel=ch,.profile=1};strcpy(p.id,name);
 p.local[0]=2;p.peer[0]=6;for(int i=1;i<6;i++)p.local[i]=p.peer[i]=name[0];
 if(role==2){p.local[0]=6;p.peer[0]=2;}memset(p.pmk,name[0],16);memset(p.lmk,name[0],16);return p;
}
static void reboot(int n){
 free(machines[n].rx);free(machines[n].rq);machines[n]=(Machine){.init=true};enterMachine(n);
 PairConfig cfg=factory[n];assert(configurationLoad(&cfg,77)==0);radio[n]=cfg;setupRadio[n]=false;
 configurationInit();leaveMachine();
}
static void reset(void){
 memset(nvSize,0,sizeof(nvSize));memset(muted,0,sizeof(muted));memset(reports,0,sizeof(reports));
 dropKind=0;clockMs=10;for(int n=1;n<=2;n++){factory[n]=makeConfig(n,11,"A-001");reboot(n);}
}
static void run(int duration){
 int64_t end=clockMs+duration;
 for(;clockMs<end;clockMs+=5)for(int n=1;n<=2;n++)if(!muted[n]){enterMachine(n);configurationTick(clockMs);leaveMachine();}
}
static void request(int n,const char*op,const void*data,int size){
 enterMachine(n);Request r={.token=42,.size=size};strcpy(r.op,op);if(size)memcpy(r.data,data,size);
 handleRequest(&r,clockMs);leaveMachine();
}
static void begin(void){PairConfig p=makeConfig(2,6,"B-002");request(2,"PAIR",&p,sizeof(p));}
static void synced(const char*id,int ch){
 for(int n=1;n<=2;n++){assert(machines[n].j.phase==CLEAN);assert(!strcmp(machines[n].j.active.id,id));assert(machines[n].j.active.channel==ch);assert(machines[n].j.active.role==n);}
}
int main(void){
 reset();begin();run(6000);synced("B-002",6);assert(strstr(reports[2]," OK "));reboot(1);reboot(2);run(100);synced("B-002",6);
 reset();muted[1]=true;begin();run(18000);synced("A-001",11);assert(strstr(reports[2],"ROLLED_BACK"));
 reset();dropKind=PROOF;begin();run(24000);synced("A-001",11);assert(strstr(reports[2],"ROLLED_BACK"));
 reset();dropKind=DONE;begin();run(24000);synced("B-002",6);assert(strstr(reports[2],"UNCONFIRMED"));
 reset();dropKind=HERE;begin();run(20000);assert(machines[1].j.phase==FOLLOW);reboot(1);reboot(2);dropKind=0;run(6000);synced("B-002",6);
 reset();begin();run(200);reboot(1);reboot(2);run(20000);synced("B-002",6);
 // The physical setup action is explicit and discovery selects a hardware unit + nonce.
 reset();enterMachine(1);configurationEnterSpare();leaveMachine();request(2,"BRIDGE",NULL,0);run(2000);
 assert(machines[1].m==SPARE && machines[2].m==BRIDGE);Node selected=machines[2].discovered[0];assert(selected.nonce);
 uint8_t payload[SELECTION_SIZE+sizeof(PairConfig)]={0};memcpy(payload+1,selected.mac,6);memcpy(payload+7,&selected.nonce,8);
 PairConfig desired=makeConfig(1,3,"C-spare");memcpy(payload+SELECTION_SIZE,&desired,sizeof(desired));
 payload[7]^=1;request(2,"SPARE",payload,sizeof(payload));assert(strstr(reports[2],"NOT_FOUND"));payload[7]^=1;
 dropKind=EXIT_SETUP;request(2,"SPARE",payload,sizeof(payload));run(3000);assert(strstr(reports[2]," OK "));
 assert(!strcmp(machines[1].j.active.id,"C-spare"));assert(machines[1].j.active.role==1);
 run(12000);assert(machines[1].m==NORMAL);reboot(1);run(100);assert(!strcmp(machines[1].j.active.id,"C-spare"));
 request(2,"END",NULL,0);assert(machines[2].m==NORMAL);assert(!strcmp(machines[2].j.active.id,"A-001"));
 puts("PASS: production configuration state machine: ID/channel commit, reboot persistence, absent peer, dropped proof/final ACK/commit message, restart recovery, spare selection nonce, saved spare and lost-exit recovery");
 return 0;
}
'''
source=re.sub(r'^#include .*?$','',(ROOT/'main/configuration.c').read_text(),flags=re.M)
link=(ROOT/'main/link.c').read_text()
validator=link[link.index('bool linkValidConfig('):link.index('esp_err_t linkReadSetup(')]
with tempfile.TemporaryDirectory() as folder:
    path=Path(folder);(path/'simulation.c').write_text(platform+validator+source+simulation)
    lib=path/'simulation.so'
    subprocess.run([os.environ.get('CC','cc'),'-std=c11','-fPIC','-shared','-nostdlib',
                    *shlex.split(os.environ.get('CFLAGS','')),str(path/'simulation.c'),'-o',str(lib)],check=True)
    assert ctypes.CDLL(str(lib)).main()==0
