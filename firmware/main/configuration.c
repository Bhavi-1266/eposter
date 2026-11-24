#include "configuration.h"
#include "channel.h"
#include "board.h"
#include "esp_crc.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "mbedtls/md.h"
#include "nvs.h"
#include "freertos/queue.h"
#include <inttypes.h>
#include <stddef.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CFG_MAGIC 0x31474643u
#define MAX_NODES 6
#define SELECTION_SIZE 15 // slot + hardware address + setup-session nonce
enum { NORMAL, PAIR_CHANGE, BRIDGE, SPARE };
enum { CLEAN, FOLLOW, VERIFY, CONFIRM };
enum { OFFER=1, CHALLENGE, PROOF, WHERE, HERE, DONE, READ, INFO,
       ADVERTISE, IDENTIFY, WRITE, WRITTEN, EXIT_SETUP };
typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint8_t version, kind;
    uint16_t length;
    uint32_t token;
    uint64_t nonce;
    uint8_t data[160], tag[16];
} Packet;
_Static_assert(sizeof(Packet) <= 250, "ESP-NOW v1 payload limit");
typedef struct { uint8_t mac[6]; Packet packet; } Received;
typedef struct { uint32_t token; char op[12]; uint16_t size; uint8_t data[160]; } Request;
typedef struct {
    uint32_t factoryTag, token;
    uint8_t phase, reserved[3];
    PairConfig active, pending;
} Journal;
typedef struct __attribute__((packed)) {
    uint8_t mac[6]; uint64_t nonce;
    uint8_t role, channel, profile, chip, mode;
    char id[65];
} Node;
static Journal journal;
static nvs_handle_t storage;
static QueueHandle_t received, requests;
static atomic_bool busy, enterSpare, syncChannel;
static atomic_int mode;
static atomic_llong identifyUntil;
static uint64_t bootNonce;
static int64_t started, lastSend, expires, savedUntil;
static bool initial = true, onCandidate, spareWritten;
static Node nodes[MAX_NODES];
static int64_t seen[MAX_NODES];
static Request waiting;
static uint8_t waitingMac[6];
static uint64_t waitingNonce;
static int64_t waitStarted, waitSent;
static const uint8_t broadcast[6] = {255,255,255,255,255,255};

static bool equalBinding(const PairConfig *a, const PairConfig *b, bool opposite)
{
    return a->channel == b->channel && !strcmp(a->id, b->id) &&
        !memcmp(a->pmk, b->pmk, 16) && !memcmp(a->lmk, b->lmk, 16) &&
        !memcmp(a->local, opposite ? b->peer : b->local, 6) &&
        !memcmp(a->peer, opposite ? b->local : b->peer, 6) &&
        a->role == (opposite ? 3 - b->role : b->role);
}

static void persist(void)
{
    ESP_ERROR_CHECK(nvs_set_blob(storage, "journal", &journal, sizeof(journal)));
    ESP_ERROR_CHECK(nvs_commit(storage));
    Journal readback; size_t size = sizeof(readback);
    ESP_ERROR_CHECK(nvs_get_blob(storage, "journal", &readback, &size));
    if (size != sizeof(journal) || memcmp(&readback, &journal, size)) abort();
}

esp_err_t configurationLoad(PairConfig *cfg, uint32_t factoryTag)
{
    esp_err_t err = nvs_open("remote_setup", NVS_READWRITE, &storage);
    if (err != ESP_OK) return err;
    size_t size = sizeof(journal);
    err = nvs_get_blob(storage, "journal", &journal, &size);
    if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND) return err;
    if (err != ESP_OK || size != sizeof(journal) || journal.factoryTag != factoryTag ||
        !linkValidConfig(&journal.active) || journal.active.role != cfg->role || journal.phase > CONFIRM ||
        (journal.phase && (!linkValidConfig(&journal.pending) || journal.pending.role != cfg->role))) {
        journal = (Journal){.factoryTag=factoryTag, .active=*cfg};
    }
    *cfg = journal.active;
    busy = journal.phase != CLEAN;
    mode = busy ? PAIR_CHANGE : NORMAL;
    return ESP_OK;
}

void configurationInit(void)
{
    received = xQueueCreate(12, sizeof(Received));
    requests = xQueueCreate(3, sizeof(Request));
    configASSERT(received && requests);
    esp_fill_random(&bootNonce, sizeof(bootNonce));
    if (!bootNonce) bootNonce = 1;
}

bool configurationReceive(const uint8_t mac[6], const void *data, int size)
{
    if (size != sizeof(Packet)) return false;
    Received item;
    memcpy(&item.packet, data, sizeof(item.packet));
    if (item.packet.magic != CFG_MAGIC) return false;
    if (!received || !linkHasSetupKey()) return true;
    memcpy(item.mac, mac, 6);
    xQueueSend(received, &item, 0);
    return true;
}

static void sign(Packet *p)
{
    uint8_t digest[32];
    int err = mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), linkSetupKey(), 16,
                            (const uint8_t *)p, offsetof(Packet, tag), digest);
    if (err) abort();
    memcpy(p->tag, digest, 16);
}

static bool authentic(const Packet *p)
{
    if (p->version != 1 || p->length > sizeof(p->data)) return false;
    Packet check = *p; sign(&check);
    unsigned diff = 0;
    for (unsigned i=0; i<16; ++i) diff |= p->tag[i] ^ check.tag[i];
    return diff == 0;
}

static void sendTo(const uint8_t mac[6], unsigned kind, uint32_t token, uint64_t nonce,
                   const void *data, size_t size)
{
    if (size > sizeof(((Packet *)0)->data)) return;
    Packet p = {.magic=CFG_MAGIC, .version=1, .kind=kind, .length=size, .token=token, .nonce=nonce};
    if (size) memcpy(p.data, data, size);
    sign(&p);
    linkSendData(mac, &p, sizeof(p));
}

static void sendPeer(unsigned kind, const void *data, size_t size)
{
    PairConfig current; linkGetConfig(&current);
    sendTo(current.peer, kind, journal.token, 0, data, size);
}

static void reply(uint32_t token, const char *status, const void *data, size_t size)
{
    char hex[2 * MAX_NODES * sizeof(Node) + 1];
    const uint8_t *bytes = data;
    if (size > (sizeof(hex)-1)/2) return;
    static const char digits[] = "0123456789abcdef";
    for (size_t i=0; i<size; ++i) { hex[2*i]=digits[bytes[i]>>4]; hex[2*i+1]=digits[bytes[i]&15]; }
    hex[2*size] = 0;
    stationMessage("RCFG %08" PRIx32 " %s %s\n", token, status, size ? hex : "-");
}

static void snapshot(void)
{
    linkGetConfig(&journal.active);
    journal.active.channel = channelCurrent();
}

static void resumeNormal(void)
{
    ESP_ERROR_CHECK(linkSwitchConfig(&journal.active, false));
    syncChannel = true;
    mode = NORMAL; busy = false;
    waiting.token = 0;
    ESP_LOGI("setup", "Normal operation: %s channel %u", journal.active.id, journal.active.channel);
}

static void selectCandidate(bool candidate)
{
    if (candidate == onCandidate) return;
    ESP_ERROR_CHECK(linkSwitchConfig(candidate ? &journal.pending : &journal.active, false));
    onCandidate = candidate;
    lastSend = 0;
}

static void beginSetup(unsigned newMode, int64_t now)
{
    snapshot();
    if (journal.phase) { journal.phase=CLEAN; persist(); }
    busy=true; mode=newMode; expires=now+180000; lastSend=0; spareWritten=false;
    esp_fill_random(&bootNonce, sizeof(bootNonce));
    if (!bootNonce) bootNonce=1;
    memset(nodes,0,sizeof(nodes)); memset(seen,0,sizeof(seen));
    ESP_ERROR_CHECK(linkSwitchConfig(&journal.active, true));
    ESP_LOGI("setup", "%s configuration on channel 11 for 180 seconds",
             newMode==BRIDGE ? "Staff bridge" : "Nearby remote");
}

static Node selfNode(void)
{
    Node n = {.nonce=bootNonce, .role=journal.active.role, .channel=journal.active.channel,
              .profile=journal.active.profile, .mode=mode};
#if CONFIG_IDF_TARGET_ESP32C3
    n.chip=3;
#else
    n.chip=32;
#endif
    linkHardwareAddress(n.mac); memcpy(n.id,journal.active.id,sizeof(n.id));
    return n;
}

static void handlePacket(const Received *item, int64_t now)
{
    const Packet *p=&item->packet;
    if (!authentic(p)) return;
    PairConfig current; linkGetConfig(&current);
    if (mode==BRIDGE || mode==SPARE) {
        if (p->kind==ADVERTISE && p->length==sizeof(Node)) {
            Node node; memcpy(&node,p->data,sizeof(node));
            if (memcmp(node.mac,item->mac,6) || !memchr(node.id,0,sizeof(node.id)) || !node.nonce ||
                !((mode==BRIDGE && node.mode==SPARE) || (mode==SPARE && node.mode==BRIDGE))) return;
            if (mode==BRIDGE) {
                int slot=-1;
                for (int i=0;i<MAX_NODES;i++) if (!memcmp(nodes[i].mac,item->mac,6)) {slot=i;break;}
                if (slot<0) for (int i=0;i<MAX_NODES;i++) if (!seen[i] || now-seen[i]>10000) {slot=i;break;}
                if (slot<0) return;
                if (seen[slot] && memcmp(nodes[slot].mac,item->mac,6)) linkForgetSetupPeer(nodes[slot].mac);
                if (linkSetupPeer(item->mac)!=ESP_OK) return;
                nodes[slot]=node;seen[slot]=now;
            } else if (linkSetupPeer(item->mac)!=ESP_OK) return;
            return;
        }
        if (mode==SPARE && p->nonce==bootNonce) {
            if (p->kind==IDENTIFY) { identifyUntil=now*1000+3000000; return; }
            if (p->kind==WRITE && p->length==sizeof(PairConfig)) {
                PairConfig desired; memcpy(&desired,p->data,sizeof(desired));
                if (!linkValidConfig(&desired) || desired.role!=journal.active.role ||
                    desired.profile!=journal.active.profile) return;
                // One committed write per physical setup session. Retries are idempotent.
                if (spareWritten && memcmp(&desired,&journal.active,sizeof(desired))) return;
                if (!spareWritten) {
                    journal.active=desired; journal.phase=CLEAN; journal.token=p->token;
                    persist(); spareWritten=true; savedUntil=now+10000;
                }
                sendTo(item->mac,WRITTEN,p->token,bootNonce,&journal.active,sizeof(journal.active));
            } else if (p->kind==EXIT_SETUP && spareWritten && p->token==journal.token) resumeNormal();
        } else if (mode==BRIDGE && waiting.token==p->token && p->kind==WRITTEN &&
                   p->nonce==waitingNonce && !memcmp(item->mac,waitingMac,6) && p->length==sizeof(PairConfig)) {
            PairConfig saved, desired;
            memcpy(&saved,p->data,sizeof(saved)); memcpy(&desired,waiting.data+SELECTION_SIZE,sizeof(desired));
            if (memcmp(&saved,&desired,sizeof(saved))) return;
            sendTo(item->mac,EXIT_SETUP,p->token,p->nonce,NULL,0);
            reply(waiting.token,"OK",&saved,sizeof(saved)); waiting.token=0;
        }
        return;
    }
    // Normal/pair-management packets must come from the currently selected peer.
    if (memcmp(item->mac,current.peer,6)) return;
    if (p->kind==READ) {
        PairConfig active=journal.phase ? journal.active : current;
        if (!journal.phase) active.channel=channelCurrent();
        sendTo(item->mac,INFO,p->token,0,&active,sizeof(active));
        return;
    }
    if (waiting.token==p->token && p->kind==INFO && p->length==sizeof(PairConfig) && !strcmp(waiting.op,"PEER")) {
        reply(waiting.token,"OK",p->data,p->length);waiting.token=0;return;
    }
    if (current.role==ROLE_HANDHELD) {
        if (p->kind==OFFER && p->length==sizeof(PairConfig) && !journal.phase && !channelBusy()) {
            PairConfig desired;memcpy(&desired,p->data,sizeof(desired));
            if (!linkValidConfig(&desired) || desired.role!=current.role) return;
            desired.profile=current.profile; // LAN never changes the hardware wiring profile.
            memcpy(desired.generation,current.generation,sizeof(desired.generation));
            snapshot(); journal.pending=desired;journal.token=p->token;journal.phase=FOLLOW;
            persist();busy=true;mode=PAIR_CHANGE;started=now;onCandidate=false;
            selectCandidate(true);
        } else if (journal.phase==FOLLOW && p->token==journal.token && p->kind==CHALLENGE && onCandidate) {
            sendPeer(PROOF,&journal.pending,sizeof(journal.pending));
        } else if (p->kind==HERE && p->length==sizeof(PairConfig)) {
            PairConfig authority;memcpy(&authority,p->data,sizeof(authority));
            if (!equalBinding(&current,&authority,true)) return;
            if (journal.phase==FOLLOW && p->token==journal.token) {
                journal.active=current;journal.phase=CLEAN;persist();
                syncChannel=true;mode=NORMAL;busy=false;
            }
            if (!journal.phase) sendTo(item->mac,DONE,p->token,0,&journal.active,sizeof(journal.active));
        }
    } else {
        if (journal.phase==VERIFY && onCandidate && p->token==journal.token &&
            p->kind==PROOF && p->length==sizeof(PairConfig)) {
            PairConfig follower;memcpy(&follower,p->data,sizeof(follower));
            if (!equalBinding(&journal.pending,&follower,true)) return;
            journal.active=journal.pending;journal.phase=CONFIRM;persist();
            started=now;lastSend=0;
        } else if (journal.phase==CONFIRM && p->token==journal.token && p->kind==DONE && p->length==sizeof(PairConfig)) {
            PairConfig follower;memcpy(&follower,p->data,sizeof(follower));
            if (!equalBinding(&journal.active,&follower,true)) return;
            journal.phase=CLEAN;persist();
            reply(journal.token,"OK",&journal.active,sizeof(journal.active));
            syncChannel=true;mode=NORMAL;busy=false;
        } else if (journal.phase!=VERIFY && p->kind==WHERE) {
            sendTo(item->mac,HERE,p->token,0,&journal.active,sizeof(journal.active));
        }
    }
}

static void handleRequest(Request *r, int64_t now)
{
    if (!strcmp(r->op,"GET")) {
        PairConfig active=journal.active;
        if (mode==NORMAL) {linkGetConfig(&active);active.channel=channelCurrent();}
        uint8_t out[122];memcpy(out,&active,sizeof(active));out[120]=mode;out[121]=journal.phase;
        reply(r->token,"OK",out,sizeof(out));return;
    }
    if (!linkHasSetupKey()) {reply(r->token,"NEEDS_FLASH",NULL,0);return;}
    if (!strcmp(r->op,"SCAN") && mode==BRIDGE) {
        Node list[MAX_NODES];memset(list,0,sizeof(list));
        for(int i=0;i<MAX_NODES;i++) if(seen[i] && now-seen[i]<10000) list[i]=nodes[i];
        expires=now+180000;reply(r->token,"OK",list,sizeof(list));return;
    }
    if (!strcmp(r->op,"END") && (mode==BRIDGE || mode==SPARE || mode==NORMAL)) {
        if (waiting.token) {reply(r->token,"BUSY",NULL,0);return;}
        if (mode!=NORMAL) resumeNormal();
        reply(r->token,"OK",NULL,0);return;
    }
    if (waiting.token || (busy && mode!=BRIDGE) || channelBusy()) {reply(r->token,"BUSY",NULL,0);return;}
    if (!strcmp(r->op,"BRIDGE") && mode==NORMAL && linkRole()==ROLE_STATION) {
        beginSetup(BRIDGE,now);reply(r->token,"OK",NULL,0);
    } else if ((!strcmp(r->op,"IDENTIFY") || !strcmp(r->op,"SPARE")) && mode==BRIDGE && r->size>=SELECTION_SIZE) {
        unsigned slot=r->data[0];
        if (slot>=MAX_NODES || !seen[slot] || now-seen[slot]>=10000) {reply(r->token,"NOT_FOUND",NULL,0);return;}
        if (memcmp(r->data+1,nodes[slot].mac,6) || memcmp(r->data+7,&nodes[slot].nonce,8)) {
            reply(r->token,"NOT_FOUND",NULL,0);return;
        }
        expires=now+180000;
        if (!strcmp(r->op,"IDENTIFY") && r->size==SELECTION_SIZE) {
            sendTo(nodes[slot].mac,IDENTIFY,r->token,nodes[slot].nonce,NULL,0);
            reply(r->token,"SENT",NULL,0);
        } else if (!strcmp(r->op,"SPARE") && r->size==SELECTION_SIZE+sizeof(PairConfig)) {
            PairConfig cfg;memcpy(&cfg,r->data+SELECTION_SIZE,sizeof(cfg));
            if (!linkValidConfig(&cfg) || cfg.role!=nodes[slot].role || cfg.profile!=nodes[slot].profile) {
                reply(r->token,"INVALID",NULL,0);return;
            }
            waiting=*r;memcpy(waitingMac,nodes[slot].mac,6);waitingNonce=nodes[slot].nonce;
            waitStarted=now;waitSent=0;
        } else reply(r->token,"INVALID",NULL,0);
    } else if (!strcmp(r->op,"PAIR") && mode==NORMAL && r->size==sizeof(PairConfig) && linkRole()==ROLE_STATION) {
        PairConfig cfg;memcpy(&cfg,r->data,sizeof(cfg));
        if (!linkValidConfig(&cfg) || cfg.role!=linkRole() || cfg.profile!=linkProfile()) {
            reply(r->token,"INVALID",NULL,0);return;
        }
        snapshot();journal.pending=cfg;journal.token=r->token;journal.phase=VERIFY;
        persist();busy=true;mode=PAIR_CHANGE;started=now;lastSend=0;onCandidate=false;
    } else if (!strcmp(r->op,"PEER") && mode==NORMAL && linkRole()==ROLE_STATION) {
        waiting=*r;waitStarted=now;waitSent=0;
    } else reply(r->token,"INVALID",NULL,0);
}

bool configurationTick(int64_t now)
{
    if (initial) {
        initial=false;started=now;
        if (journal.phase) {
            onCandidate=false;
            if (journal.phase==FOLLOW || journal.phase==CONFIRM) selectCandidate(true);
        }
    }
    if (atomic_exchange(&enterSpare,false) && mode==NORMAL && !channelBusy() && linkHasSetupKey()) beginSetup(SPARE,now);
    Request request;
    if (xQueueReceive(requests,&request,0)) handleRequest(&request,now);
    Received item;
    for (int i=0;i<12 && xQueueReceive(received,&item,0);i++) handlePacket(&item,now);
    if (waiting.token) {
        if (now-waitStarted>8000) {reply(waiting.token,"UNCONFIRMED",NULL,0);waiting.token=0;}
        else if (now-waitSent>=200) {
            if (!strcmp(waiting.op,"PEER")) {
                PairConfig cfg;linkGetConfig(&cfg);sendTo(cfg.peer,READ,waiting.token,0,NULL,0);
            } else sendTo(waitingMac,WRITE,waiting.token,waitingNonce,waiting.data+SELECTION_SIZE,sizeof(PairConfig));
            waitSent=now;
        }
    }
    if (mode==BRIDGE || mode==SPARE) {
        if (now>=expires || (mode==SPARE && spareWritten && now>=savedUntil)) {
            if(waiting.token) reply(waiting.token,"UNCONFIRMED",NULL,0);
            resumeNormal();
        } else if (now-lastSend>=500) {
            Node n=selfNode();sendTo(broadcast,ADVERTISE,0,bootNonce,&n,sizeof(n));lastSend=now;
        }
        return busy;
    }
    if (journal.phase==FOLLOW) {
        bool old = now-started>=1800 && ((now-started-1800)/700)%2==0;
        selectCandidate(!old);
        if (now-lastSend>=100) {sendPeer(WHERE,NULL,0);lastSend=now;}
    } else if (journal.phase==VERIFY) {
        if (now-started>=15000) {
            selectCandidate(false);journal.phase=CLEAN;persist();
            reply(journal.token,"ROLLED_BACK",&journal.active,sizeof(journal.active));
            syncChannel=true;mode=NORMAL;busy=false;
        } else {
            bool candidate=(now-started)%1600>=650;
            selectCandidate(candidate);
            if (now-lastSend>=120) {
                PairConfig follower=journal.pending;
                follower.role=ROLE_HANDHELD;
                memcpy(follower.local,journal.pending.peer,6);memcpy(follower.peer,journal.pending.local,6);
                sendPeer(candidate ? CHALLENGE : OFFER,candidate ? NULL : &follower,candidate ? 0 : sizeof(follower));
                lastSend=now;
            }
        }
    } else if (journal.phase==CONFIRM) {
        if (now-started>=15000) {
            journal.phase=CLEAN;persist();
            reply(journal.token,"UNCONFIRMED",&journal.active,sizeof(journal.active));
            syncChannel=true;mode=NORMAL;busy=false;
        } else if (now-lastSend>=100) {sendPeer(HERE,&journal.active,sizeof(journal.active));lastSend=now;}
    }
    return busy;
}

bool configurationBusy(void) { return busy; }
bool configurationNeedsChannelSync(void) { return atomic_exchange(&syncChannel,false); }
void configurationEnterSpare(void) { if (linkRole()==ROLE_HANDHELD) enterSpare=true; }
bool configurationLed(int64_t nowUs)
{
    if (mode!=SPARE) return false;
    bool on = nowUs<identifyUntil ? (nowUs/80000)%2 : (nowUs/400000)%2;
    gpio_set_level(STATUS_LED,!on);return true;
}

static int nibble(char c)
{
    if(c>='0' && c<='9') return c-'0';
    if(c>='a' && c<='f') return c-'a'+10;
    return -1;
}
void configurationCommand(uint32_t token, const char *operation, const char *hex)
{
    Request r={.token=token};
    size_t n=strlen(hex);
    if (!token || strlen(operation)>=sizeof(r.op) || (strcmp(hex,"-") && (n%2 || n>sizeof(r.data)*2))) {
        reply(token,"INVALID",NULL,0);return;
    }
    strcpy(r.op,operation);
    if(strcmp(hex,"-")) {
        r.size=n/2;
        for(unsigned i=0;i<r.size;i++) {
            int a=nibble(hex[2*i]),b=nibble(hex[2*i+1]);
            if(a<0 || b<0) {reply(token,"INVALID",NULL,0);return;}
            r.data[i]=(a<<4)|b;
        }
    }
    if(!requests || !xQueueSend(requests,&r,0)) reply(token,"BUSY",NULL,0);
}
