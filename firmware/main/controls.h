#pragma once
#include <stdint.h>
#include <stdbool.h>
void matrixInit(void);
uint16_t matrixScan(void);
void controlsInit(void);
uint16_t batteryMillivolts(void);
void startStaffCalibration(void);
void cycleSensitivity(void);
bool staffCalibrationActive(void);
bool readMotion(bool aim, bool keysDown, int16_t *dx, int16_t *dy);
void updateStatusLed(bool pressed, bool aim, int64_t now);
void controlsSleep(void);

void captureWakeKeys(void);
