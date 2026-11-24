#include "link.h"
#include "nvs.h"
#include "controls.h"
#include "board.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "driver/i2c_master.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "esp_sleep.h"
#include "esp_wifi.h"
#include "esp_timer.h"

static const gpio_num_t rows[] = {ROW1, ROW2, ROW3};
static const gpio_num_t cols[] = {COL1, COL2, COL3};
static adc_oneshot_unit_handle_t adc;
static adc_cali_handle_t calibration;
static i2c_master_dev_handle_t mpu;
enum { MPU6050_ID = 0x68, MPU6500_ID = 0x70 };
static uint8_t mpuId, mpuAddress;
static bool asleep, calibrated;
static float biasX, biasZ, fractionX, fractionY;
static int64_t nextSample, previousMotion;
typedef struct { float x, z; uint8_t version, id, address, reserved; } GyroBias;
static nvs_handle_t prefs;
static bool havePrefs;
static const unsigned gains[] = {6, 9, 15};
static uint8_t speed = 1;
static int64_t calibrationDeadline, feedbackStart;
static unsigned feedbackPulses;
static struct { unsigned count; float x, z, xx, zz; } samples;

static void loadMotionSettings(void)
{
    esp_err_t err = nvs_open("presenter_imu", NVS_READWRITE, &prefs);
    havePrefs = err == ESP_OK;
    if (!havePrefs) {
        ESP_LOGE("inputs", "Cannot open saved settings: %s", esp_err_to_name(err));
        return;
    }
    uint8_t level;
    if (nvs_get_u8(prefs, "speed", &level) == ESP_OK && level < 3) speed = level;
    GyroBias saved;
    size_t size = sizeof(saved);
    err = nvs_get_blob(prefs, "bias", &saved, &size);
    if (err == ESP_OK && size == sizeof(saved) && saved.version == 1 &&
        saved.id == mpuId && saved.address == mpuAddress &&
        fabsf(saved.x) <= 8 && fabsf(saved.z) <= 8) {
        biasX = saved.x; biasZ = saved.z; calibrated = true;
        ESP_LOGI("inputs", "AIM ready from saved calibration, sensitivity %u/3", speed + 1);
    } else {
        ESP_LOGW("inputs", "AIM needs staff calibration: hold AIM and tap Home");
    }
}

bool staffCalibrationActive(void) { return calibrationDeadline != 0; }

void startStaffCalibration(void)
{
    if (!mpu || !havePrefs) {
        ESP_LOGW("inputs", "Calibration unavailable: check sensor and settings storage");
        return;
    }
    calibrationDeadline = esp_timer_get_time() + 20000000;
    memset(&samples, 0, sizeof(samples));
    fractionX = fractionY = 0;
    previousMotion = 0;
    ESP_LOGI("inputs", "Staff calibration started: release buttons and leave the remote still");
}

void cycleSensitivity(void)
{
    if (!mpu || !havePrefs) return;
    uint8_t level = (speed + 1) % 3;
    esp_err_t err = nvs_set_u8(prefs, "speed", level);
    if (err == ESP_OK) err = nvs_commit(prefs);
    if (err == ESP_OK) {
        speed = level;
        feedbackPulses = speed + 1;
        feedbackStart = esp_timer_get_time();
        ESP_LOGI("inputs", "AIM sensitivity %u/3", speed + 1);
    } else ESP_LOGE("inputs", "Sensitivity save failed: %s", esp_err_to_name(err));
}

void updateStatusLed(bool pressed, bool aim, int64_t now)
{
    static int64_t pressUntil;
    if (pressed) pressUntil = now + 80000;
    bool on = now < pressUntil;
    if (staffCalibrationActive()) on = (now / 250000) % 2 == 0;
    else if (feedbackPulses && now - feedbackStart < feedbackPulses * 300000LL)
        on = ((now - feedbackStart) / 150000) % 2 == 0;
    else if (aim && !calibrated) on = (now / 120000) % 2 == 0;
    // Setup mode also drives this pin, so always restore the current normal state.
    gpio_set_level(STATUS_LED, !on);
}

void matrixInit(void)
{
    // Prepare LED OFF before releasing its retained sleep state.
    ESP_ERROR_CHECK(gpio_reset_pin(STATUS_LED));
    ESP_ERROR_CHECK(gpio_set_level(STATUS_LED, 1));
    ESP_ERROR_CHECK(gpio_set_direction(STATUS_LED, GPIO_MODE_OUTPUT));
    ESP_ERROR_CHECK(gpio_hold_dis(STATUS_LED));
    gpio_deep_sleep_hold_dis();
    const bool oneButton = linkProfile() == PROFILE_ONE_BUTTON;
    if (oneButton || linkProfile() == PROFILE_TWO_BUTTON) {
        gpio_hold_dis(BENCH_OK_GPIO);
        uint64_t pins = 1ULL << BENCH_OK_GPIO;
        if (!oneButton) {
            gpio_hold_dis(BENCH_AIM_GPIO);
            gpio_hold_dis(COL3);
            pins |= 1ULL << BENCH_AIM_GPIO;
        }
        const gpio_config_t buttons = {
            .pin_bit_mask = pins,
            .mode = GPIO_MODE_INPUT,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_ENABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        ESP_ERROR_CHECK(gpio_config(&buttons));
        ESP_LOGI("inputs", "Play/pause on GPIO%d, active high", BENCH_OK_GPIO);
        if (!oneButton) ESP_LOGI("inputs", "Hold GPIO%d high to AIM", BENCH_AIM_GPIO);
    } else {
        for (int i = 0; i < 3; i++) {
            gpio_hold_dis(cols[i]);
            gpio_reset_pin(cols[i]);
            gpio_pullup_dis(cols[i]);
            gpio_reset_pin(rows[i]);
            gpio_set_direction(rows[i], GPIO_MODE_INPUT);
            gpio_set_pull_mode(rows[i], MATRIX_ACTIVE ? GPIO_PULLDOWN_ONLY : GPIO_PULLUP_ONLY);
            gpio_set_level(cols[i], MATRIX_ACTIVE);
            gpio_set_direction(cols[i], GPIO_MODE_INPUT);
        }
    }
}

uint16_t matrixScan(void)
{
    uint16_t pressed = 0;
    const bool aimSwitch = linkProfile() == PROFILE_TWO_BUTTON;
    if (aimSwitch || linkProfile() == PROFILE_ONE_BUTTON) {
        if (gpio_get_level(BENCH_OK_GPIO)) pressed |= 1u << KEY_OK_INDEX;
        if (aimSwitch && gpio_get_level(BENCH_AIM_GPIO)) pressed |= 1u << KEY_AIM_INDEX;
    } else {
        for (int col = 0; col < 3; col++) {
            gpio_set_direction(cols[col], GPIO_MODE_OUTPUT);
            esp_rom_delay_us(15);
            for (int row = 0; row < 3; row++)
                if (gpio_get_level(rows[row]) == MATRIX_ACTIVE) pressed |= 1u << (3 * row + col);
            gpio_set_direction(cols[col], GPIO_MODE_INPUT);
        }
    }
    return pressed;
}

static bool mpuWrite(uint8_t reg, uint8_t value)
{
    uint8_t command[] = {reg, value};
    return i2c_master_transmit(mpu, command, sizeof(command), 15) == ESP_OK;
}

// Confirm the sensor accepted each sleep/wake transition before trusting its state.
static bool setMpuSleep(bool sleep)
{
    const uint8_t reg = 0x6b;
    uint8_t value;
    if (!mpuWrite(reg, sleep ? 0x40 : 1) ||
        i2c_master_transmit_receive(mpu, &reg, 1, &value, 1, 15) != ESP_OK ||
        ((value & 0x40) != 0) != sleep) return false;
    asleep = sleep;
    ESP_LOGI("power", "MPU %s verified (PWR_MGMT_1=0x%02x)", sleep ? "sleep" : "awake", value);
    return true;
}

void controlsInit(void)
{
    /* The single-switch battery fixture has neither an IMU nor a voltage divider. */
    if (linkProfile() == PROFILE_ONE_BUTTON) return;
    adc_oneshot_unit_init_cfg_t unit = {.unit_id = ADC_UNIT_1};
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&unit, &adc));
    adc_oneshot_chan_cfg_t chan = {.atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT};
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc, BAT_CHANNEL, &chan));
#if ADC_CALI_SCHEME_CURVE_FITTING_SUPPORTED
    adc_cali_curve_fitting_config_t cfg = {.unit_id = ADC_UNIT_1, .chan = BAT_CHANNEL,
        .atten = chan.atten, .bitwidth = chan.bitwidth};
    if (adc_cali_create_scheme_curve_fitting(&cfg, &calibration) != ESP_OK)
        calibration = NULL;
#else
    adc_cali_line_fitting_config_t cfg = {.unit_id=ADC_UNIT_1, .atten=chan.atten, .bitwidth=chan.bitwidth, .default_vref=1100};
    if (adc_cali_create_scheme_line_fitting(&cfg, &calibration) != ESP_OK) calibration = NULL;
#endif
    i2c_master_bus_config_t busCfg = {.i2c_port = 0, .sda_io_num = MPU_SDA,
        .scl_io_num = MPU_SCL, .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true};
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&busCfg, &bus));
    uint8_t address = MPU_ADDRESS;
    esp_err_t firstProbe = i2c_master_probe(bus, address, 20);
    if (firstProbe != ESP_OK) {
        address = MPU_ADDRESS_AD0_HIGH;
        esp_err_t secondProbe = i2c_master_probe(bus, address, 20);
        if (secondProbe != ESP_OK) {
            ESP_LOGW("inputs", "MPU probe: 0x68=%s, 0x69=%s. SDA GPIO%d=%d, SCL GPIO%d=%d",
                     esp_err_to_name(firstProbe), esp_err_to_name(secondProbe),
                     MPU_SDA, gpio_get_level(MPU_SDA), MPU_SCL, gpio_get_level(MPU_SCL));
            ESP_LOGI("inputs", "I2C scan 0x08..0x77 on SDA GPIO%d, SCL GPIO%d", MPU_SDA, MPU_SCL);
            unsigned found = 0, errors = 0;
            for (unsigned candidate = 0x08; candidate <= 0x77; ++candidate) {
                esp_err_t result = i2c_master_probe(bus, candidate, 10);
                if (result == ESP_OK) {
                    ++found;
                    ESP_LOGI("inputs", "I2C device responds at 0x%02x", candidate);
                } else if (result != ESP_ERR_NOT_FOUND) {
                    ++errors;
                    ESP_LOGW("inputs", "I2C address 0x%02x: %s", candidate, esp_err_to_name(result));
                }
            }
            ESP_LOGI("inputs", "I2C scan complete: %u responding devices, %u bus errors", found, errors);
            return;
        }
    }
    i2c_device_config_t device = {.dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = address, .scl_speed_hz = 100000};
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &device, &mpu));
    uint8_t reg = 0x75;
    esp_err_t readId = i2c_master_transmit_receive(mpu, &reg, 1, &mpuId, 1, 15);
    if (readId != ESP_OK) {
        ESP_LOGW("inputs", "WHO_AM_I read failed at 0x%02x: %s", address, esp_err_to_name(readId));
    } else if (mpuId != MPU6050_ID && mpuId != MPU6500_ID) {
        ESP_LOGW("inputs", "Unsupported WHO_AM_I=0x%02x at 0x%02x", mpuId, address);
    } else if (mpuWrite(0x6b, 1) && mpuWrite(0x1b, 0) && mpuWrite(0x1c, 0) && mpuWrite(0x1a, 3)) {
        mpuAddress = address;
        loadMotionSettings();
        nextSample = esp_timer_get_time() + 100000;
        ESP_LOGI("inputs", "%s detected at 0x%02x (WHO_AM_I=0x%02x)",
                 mpuId == MPU6500_ID ? "MPU6500" : "MPU6050", address, mpuId);
        return;
    } else {
        ESP_LOGW("inputs", "MPU configuration write failed at 0x%02x", address);
    }
    ESP_ERROR_CHECK(i2c_master_bus_rm_device(mpu));
    mpu = NULL;
}

uint16_t batteryMillivolts(void)
{
    if (!calibration) return 0;
    int total = 0, raw = 0, mv = 0;
    for (int i = 0; i < 8; i++) {
        if (adc_oneshot_read(adc, BAT_CHANNEL, &raw) != ESP_OK) return 0;
        total += raw;
    }
    return adc_cali_raw_to_voltage(calibration, total / 8, &mv) == ESP_OK ? mv * 2 : 0;
}

static int16_t read16(const uint8_t *b)
{
    return (int16_t)((b[0] << 8) | b[1]);
}

static void finishCalibration(bool saved)
{
    calibrationDeadline = 0;
    feedbackPulses = saved ? 1 : 5;
    feedbackStart = esp_timer_get_time();
    if (!saved) ESP_LOGW("inputs", "Calibration unsuccessful; previous setting retained");
}

static void collectBias(const uint8_t *b, float x, float z)
{
    float ax = read16(b) / 16384.f, ay = read16(b+2) / 16384.f, az = read16(b+4) / 16384.f;
    float norm = ax*ax + ay*ay + az*az;
    if (norm > 0.8f && norm < 1.2f && fabsf(x) < 8 && fabsf(z) < 8 && abs(read16(b+10)) < 1048) {
        samples.x += x; samples.z += z; samples.xx += x*x; samples.zz += z*z;
        if (++samples.count < 50) return;
        float bx = samples.x / 50, bz = samples.z / 50;
        if (samples.xx / 50 - bx*bx < 0.6f && samples.zz / 50 - bz*bz < 0.6f) {
            GyroBias bias = {.version=1, .id=mpuId, .address=mpuAddress, .x=bx, .z=bz};
            esp_err_t err = nvs_set_blob(prefs, "bias", &bias, sizeof(bias));
            if (err == ESP_OK) err = nvs_commit(prefs);
            if (err == ESP_OK) {
                biasX = bx; biasZ = bz; calibrated = true;
                ESP_LOGI("inputs", "Staff calibration saved; AIM ready");
            } else ESP_LOGE("inputs", "Calibration save failed: %s", esp_err_to_name(err));
            finishCalibration(err == ESP_OK);
        }
    }
    memset(&samples, 0, sizeof(samples));
}

bool readMotion(bool aim, bool keysDown, int16_t *dx, int16_t *dy)
{
    if (!mpu) return false;
    int64_t now = esp_timer_get_time();
    if (staffCalibrationActive() && now >= calibrationDeadline) finishCalibration(false);
    if (!staffCalibrationActive() && (!calibrated || !aim)) {
        if (!asleep) setMpuSleep(true);
        fractionX = fractionY = 0;
        previousMotion = 0;
        return false;
    }
    if (asleep) {
        if (setMpuSleep(false)) {
            nextSample = now + (mpuId == MPU6500_ID ? 70000 : 50000);
        }
        return false;
    }
    if (now < nextSample) return false;
    nextSample = now + 20000;  // up to 50 motion reports/s
    uint8_t reg = 0x3b, b[14];
    if (i2c_master_transmit_receive(mpu, &reg, 1, b, sizeof(b), 15) != ESP_OK) {
        if (staffCalibrationActive()) memset(&samples, 0, sizeof(samples));
        return false;
    }
    float x = read16(b+8) / 131.0f, z = read16(b+12) / 131.0f;
    if (staffCalibrationActive()) {
        if (keysDown) memset(&samples, 0, sizeof(samples));
        else collectBias(b, x, z);
        return false;
    }
    float dt = previousMotion ? fminf((now-previousMotion)/1000000.f, 0.04f) : 0.02f;
    previousMotion = now;
    x -= biasX; z -= biasZ;
    // With the MPU mounted in this handheld, gyro Z steers across the screen and X steers vertically.
    if (fabsf(z) > 0.9f) fractionX += z * dt * gains[speed];
    if (fabsf(x) > 0.9f) fractionY += x * dt * gains[speed];
    *dx = (int16_t)fractionX; *dy = (int16_t)fractionY;
    fractionX -= *dx; fractionY -= *dy;
    return *dx || *dy;
}

void controlsSleep(void)
{
    if (mpu && !setMpuSleep(true))
        ESP_LOGW("power", "MPU sleep not confirmed; entering ESP deep sleep");
    ESP_ERROR_CHECK_WITHOUT_ABORT(esp_wifi_stop());
    ESP_ERROR_CHECK(gpio_set_level(STATUS_LED, 1));
    ESP_ERROR_CHECK(gpio_hold_en(STATUS_LED));
    uint64_t mask = 0;
    for (int i = 0; i < 3; i++) {
        gpio_set_level(cols[i], MATRIX_ACTIVE);
        gpio_set_direction(cols[i], GPIO_MODE_OUTPUT);
        ESP_ERROR_CHECK(gpio_hold_en(cols[i]));
        mask |= 1ULL << rows[i];
    }
    gpio_deep_sleep_hold_en();
#if CONFIG_IDF_TARGET_ESP32C3
    ESP_ERROR_CHECK(esp_deep_sleep_enable_gpio_wakeup(mask, ESP_GPIO_WAKEUP_GPIO_LOW));
#else
    ESP_ERROR_CHECK(esp_sleep_enable_ext1_wakeup(mask, ESP_EXT1_WAKEUP_ANY_HIGH));
#endif
    ESP_LOGI("power", "Entering deep sleep: LED OFF; any matrix key wakes the sender");
    esp_deep_sleep_start();
}
