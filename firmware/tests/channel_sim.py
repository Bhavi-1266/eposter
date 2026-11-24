"""Run the production channel state machine on two simulated radios with a C compiler."""
import ctypes, os, re, shlex, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
platform = r'''
#include <assert.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <inttypes.h>
#include <stdlib.h>
enum {ROLE_HANDHELD=1, ROLE_STATION=2, CH_OFFER=5, CH_VERIFY, CH_PROOF, CH_WHERE, CH_HERE, CH_DONE};
typedef struct {uint8_t kind; uint32_t session,sequence; int16_t x,y;} LinkPacket;
typedef int nvs_handle_t, QueueHandle_t, BaseType_t, esp_err_t;
#define ESP_ERROR_CHECK(call) assert((call)==0)
#define configASSERT assert
#define ESP_OK 0
#define ESP_LOGI(...)
#define ESP_ERR_NVS_NOT_FOUND 1
#define NVS_READWRITE 1
#define pdPASS 1
#define pdMS_TO_TICKS(x) (x)
static uint8_t who, frequency[3], nv[3][64]; static size_t nbytes[3];
static int64_t clockMs; static int dropKind, cutAtCommit; static bool muted[3]; static char report[120];
static LinkPacket inbox[3][100]; static int queued[3]; static bool written[3], restartNeeded;
int linkRole(void){return who;}
int linkDefaultChannel(void){return 6;}
uint32_t linkConfigTag(void){return 1234;}
void linkTune(uint8_t ch){frequency[who]=ch;}
LinkPacket linkPacket(uint8_t k,uint32_t s,uint32_t q){return (LinkPacket){k,s,q,0,0};}
void linkSend(LinkPacket *p){int dst=3-who;if(p->kind!=dropKind && !muted[who] && !muted[dst] && frequency[dst]==frequency[who]){assert(queued[dst]<100);inbox[dst][queued[dst]++]=*p;}}
void stationMessage(const char *fmt,...){va_list ap;va_start(ap,fmt);vsnprintf(report,sizeof(report),fmt,ap);va_end(ap);}
int64_t esp_timer_get_time(void){return clockMs*1000;}
int nvs_open(const char *a,int b,int *out){*out=1;return 0;}
int nvs_get_blob(int h,const char*k,void*p,size_t*n){if(!nbytes[who])return 1;memcpy(p,nv[who],*n);return 0;}
int nvs_set_blob(int h,const char*k,const void*p,size_t n){assert(n<=64);memcpy(nv[who],p,n);nbytes[who]=n;written[who]=true;return 0;}
int nvs_commit(int h){if(cutAtCommit==who){restartNeeded=true;cutAtCommit=0;}return 0;}
int xQueueCreate(int a,size_t b){return 1;}
int xQueueReceive(int a,void*b,int c){return 0;}
int xQueueSend(int a,void*b,int c){return 1;}
void vTaskDelay(int n){}
int xTaskCreate(void(*f)(void*),const char*n,int s,void*a,int p,void*b){return 1;}
bool linkManagement(LinkPacket*p){return false;}
bool configurationTick(int64_t now){return false;}
bool configurationNeedsChannelSync(void){return false;}
bool configurationBusy(void){return false;}
'''
sim = r'''
typedef struct {SavedChannel state; enum Stage phase; uint32_t txn; uint8_t tgt,tune; int64_t start,last; bool b;} Node;
static Node nodes[3];
static void enter(int n){who=n;Node v=nodes[n];saved=v.state;stage=v.phase;transaction=v.txn;target=v.tgt;tuned=v.tune;started=v.start;lastTx=v.last;busy=v.b;}
static void leave(void){nodes[who]=(Node){saved,stage,transaction,target,tuned,started,lastTx,busy};}
static void reboot(int n){nodes[n]=(Node){0};queued[n]=0;enter(n);channelStart();leave();}
static void reset(void){clockMs=0;memset(nbytes,0,sizeof(nbytes));memset(muted,0,sizeof(muted));report[0]=0;dropKind=0;cutAtCommit=0;restartNeeded=false;reboot(1);reboot(2);}
static void begin(void){enter(2);transaction=42;target=11;started=clockMs;lastTx=0;stage=VERIFYING;busy=true;leave();}
static void run(int duration){int64_t end=clockMs+duration;for(;clockMs<end;clockMs+=5){for(int n=1;n<=2;n++){enter(n);for(int i=0;i<queued[n];i++){if(n==1)senderStep(&inbox[n][i],clockMs);else receiverStep(&inbox[n][i],clockMs);}queued[n]=0;tick(clockMs);leave();if(restartNeeded){restartNeeded=false;reboot(n);}}}}
static void synced(int c){assert(nodes[1].state.active==c && !nodes[1].state.pending && nodes[2].state.active==c);}
int main(void){
reset();begin();run(16000);synced(11);assert(strstr(report," OK "));reboot(1);reboot(2);synced(11);
reset();muted[1]=true;begin();run(8000);synced(6);assert(strstr(report,"ROLLED_BACK"));
reset();dropKind=CH_PROOF;begin();run(15000);synced(6);assert(strstr(report,"ROLLED_BACK"));
reset();dropKind=CH_DONE;begin();run(18000);synced(11);assert(strstr(report,"COMMITTED_UNCONFIRMED"));
reset();begin();run(230);reboot(2);run(14000);synced(6);
reset();cutAtCommit=1;begin();run(18000);synced(11);
reset();cutAtCommit=2;begin();run(18000);synced(11);
reset();dropKind=CH_HERE;begin();run(14000);assert(nodes[1].state.pending==11 && nodes[2].state.active==11);reboot(1);dropKind=0;run(8000);synced(11);
puts("PASS: channel switch, asleep sender, lost proof, lost final ACK, power loss before/after commit, durable recovery");}
'''
with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)
    source=(ROOT/"main/channel.c").read_text()
    source=re.sub(r"^#include .*?$","",source,flags=re.M)
    (path/"sim.c").write_text(platform+source+sim)
    lib=path/"simulation.so"
    subprocess.run([os.environ.get("CC","cc"),"-std=c11","-fPIC","-shared","-nostdlib",
                    *shlex.split(os.environ.get("CFLAGS","")),str(path/"sim.c"),"-o",str(lib)],check=True)
    assert ctypes.CDLL(str(lib)).main() == 0
