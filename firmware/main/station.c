#include "link.h"
#include "board.h"
#include "channel.h"
#include "configuration.h"
#include <stdarg.h>
#include <string.h>
#include "driver/uart.h"
#include "esp_log.h"
#define STATION_UART UART_NUM_1
#define STATION_BAUD 115200

void stationMessage(const char *format, ...)
{
    char buf[1400];
    va_list args;
    va_start(args, format);
    int n = vsnprintf(buf, sizeof(buf), format, args);
    va_end(args);
    if (n > 0 && n < sizeof(buf)) {
        int written = uart_write_bytes(STATION_UART, buf, n);
        if (strncmp(buf,"RCFG ",5))
            ESP_LOGI("station", "UART control TX %d/%d bytes: %.*s", written, n, n, buf);
    }
}
#include <inttypes.h>
#include <stddef.h>
#include <stdio.h>

static void stationUartInit(void)
{
    const uart_config_t config = {
        .baud_rate = STATION_BAUD, .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE, .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE, .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_param_config(STATION_UART, &config));
    ESP_ERROR_CHECK(uart_set_pin(STATION_UART, STATION_TX, STATION_RX,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    ESP_ERROR_CHECK(uart_driver_install(STATION_UART, 2048, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_set_rx_timeout(STATION_UART, 2));
}

static void handleReplies(uint32_t pendingSession, uint32_t pendingSeq)
{
    static char line[400];
    static size_t used;
    static bool overflow;
    char bytes[80];
    int count = uart_read_bytes(STATION_UART, bytes, sizeof(bytes), 0);
    for (int i = 0; i < count; i++) {
        char ch = bytes[i];
        if (ch == '\r') continue;
        if (ch != '\n') {
            if (used + 1 < sizeof(line)) line[used++] = ch;
            else overflow = true;
            continue;
        }
        line[used] = 0;
        if (strncmp(line, "ACK ", 4) != 0 && strncmp(line,"RCFG ",5) != 0) {
            ESP_LOGI("station", "UART RX line (%u bytes)", (unsigned)used);
        }
        uint32_t session, sequence;
        char extra;
        char id[65];
        unsigned channel;
        uint32_t token;
        char operation[12], hex[321];
        if (!overflow && sscanf(line,"RCFG %" SCNx32 " %11s %320s %c",&token,operation,hex,&extra)==3) {
            ESP_LOGI("station","Staff configuration command %s",operation);
            configurationCommand(token,operation,hex);
        }
        if (!overflow && sscanf(line, "CHANNEL %" SCNx32 " %64s %u %c", &token, id, &channel, &extra) == 3) {
            ESP_LOGI("station", "UART control RX token=%08" PRIx32 " device=%s channel=%u", token, id, channel);
            if (!strcmp(id, linkId())) channelCommand(channel, token);
            else stationMessage("CHANNEL %08" PRIx32 " WRONG_ID 0\n", token);
        }
        if (!overflow && pendingSession &&
            sscanf(line, "ACK %" SCNx32 " %" SCNx32 " %c", &session, &sequence, &extra) == 2 &&
            session == pendingSession && sequence == pendingSeq) {
            LinkPacket ack = linkPacket(EVENT_ACK, session, sequence);
            linkSend(&ack);
        }
        used = 0;
        overflow = false;
    }
}

void runStation(void)
{
    stationUartInit();
    uint32_t unique = 0, previousSession = 0, previousSeq = 0;
    ESP_LOGI("station", "Ready. UART1 TX=%d RX=%d %d 8N1", STATION_TX, STATION_RX, STATION_BAUD);
    stationMessage("READY %s UART1 TX=%d RX=%d %d 8N1\n", linkId(), STATION_TX, STATION_RX, STATION_BAUD);
    uint32_t pendingSession = 0, pendingSeq = 0;
    char frame[100];
    for (;;) {
        LinkPacket p;
        if (linkReceive(&p, pdMS_TO_TICKS(1))) {
            if (linkProfile() == PROFILE_CROWD && p.kind == EVENT_TEST) {
                LinkPacket ack = linkPacket(EVENT_ACK, p.session, p.sequence);
                linkSend(&ack);
                if (previousSession != p.session || previousSeq != p.sequence) ++unique;
                previousSession = p.session; previousSeq = p.sequence;
                if (unique % 100 == 1) ESP_LOGI("crowd", "HELLO received=%" PRIu32, unique);
                continue;
            }
            if (p.kind != EVENT_MOVE) {
                pendingSession = p.session;
                pendingSeq = p.sequence;
            }
            int len = snprintf(frame, sizeof(frame), "EV %08" PRIx32 " %08" PRIx32 " %u %d %d %u\n",
                               p.session, p.sequence, p.kind, p.x, p.y, p.batteryMv);
            uart_write_bytes(STATION_UART, frame, len);
        }
        handleReplies(pendingSession, pendingSeq);
    }
}
