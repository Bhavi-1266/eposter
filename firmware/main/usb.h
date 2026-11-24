#pragma once
#include <stdbool.h>
#include <stddef.h>
void usbInit(void);
bool usbLine(char *line, size_t capacity);

bool consoleConnected(void);
