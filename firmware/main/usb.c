#include "usb.h"
#include "sdkconfig.h"
#if CONFIG_IDF_TARGET_ESP32C3
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "esp_err.h"

void usbInit(void)
{
    usb_serial_jtag_driver_config_t cfg = {.tx_buffer_size = 2048, .rx_buffer_size = 512};
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&cfg));
    usb_serial_jtag_vfs_use_driver();
}

bool consoleConnected(void) { return usb_serial_jtag_is_connected(); }
static int readConsole(char *ch) { return usb_serial_jtag_read_bytes(ch, 1, 0); }
#else
#include "driver/uart.h"
#include "esp_err.h"
void usbInit(void) {
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 512, 0, 0, NULL, 0));
}
bool consoleConnected(void) { return false; }
static int readConsole(char *ch) { return uart_read_bytes(UART_NUM_0, ch, 1, 0); }
#endif

bool usbLine(char *line, size_t capacity)
{
    static size_t used;
    static bool overflow;
    char ch;
    while (readConsole(&ch) == 1) {
        if (ch == '\r' || ch == '\n') {
            bool ready = used && !overflow;
            line[used] = 0;
            used = 0;
            overflow = false;
            if (ready) return true;
        } else if (used + 1 < capacity) {
            line[used++] = ch;
        } else {
            overflow = true;
        }
    }
    return false;
}
