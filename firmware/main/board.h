#pragma once
#include "driver/gpio.h"
#if CONFIG_IDF_TARGET_ESP32C3
// Receiver UART header. Handheld and receiver pin functions are mutually exclusive.
#define STATION_TX GPIO_NUM_21
#define STATION_RX GPIO_NUM_20
#define MATRIX_ACTIVE 0
#define ROW1 GPIO_NUM_0
#define ROW2 GPIO_NUM_1
#define ROW3 GPIO_NUM_3
#define COL1 GPIO_NUM_6
#define COL2 GPIO_NUM_7
#define COL3 GPIO_NUM_10
#define MPU_SDA GPIO_NUM_5
#define MPU_SCL GPIO_NUM_20
#define MPU_ADDRESS 0x68
#define MPU_ADDRESS_AD0_HIGH 0x69
#define BAT_GPIO GPIO_NUM_4
#define BAT_CHANNEL ADC_CHANNEL_4
#define STATUS_LED GPIO_NUM_21
#else
#define STATION_TX GPIO_NUM_17
#define STATION_RX GPIO_NUM_16
#define ROW1 GPIO_NUM_32
#define ROW2 GPIO_NUM_33
#define ROW3 GPIO_NUM_25
#define COL1 GPIO_NUM_16
#define COL2 GPIO_NUM_17
#define COL3 GPIO_NUM_23
#define MATRIX_ACTIVE 1
#define MPU_SDA GPIO_NUM_21
#define MPU_SCL GPIO_NUM_22
#define MPU_ADDRESS 0x68
#define MPU_ADDRESS_AD0_HIGH 0x69
#define BAT_CHANNEL ADC_CHANNEL_6
#define STATUS_LED GPIO_NUM_27
#endif
#define IDLE_SLEEP_SECONDS 33
#include "buttons.h"
#define BENCH_OK_GPIO COL1
#define BENCH_AIM_GPIO COL2
