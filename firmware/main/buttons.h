#pragma once
#include <stdbool.h>
#include <stdint.h>

enum { KEY_HOME_INDEX = 2, KEY_OK_INDEX = 4, KEY_AIM_INDEX = 6, KEY_MODE_INDEX = 8 };
// S9 / KEY_MODE_INDEX is reserved; the handheld excludes it from actions and chords.

typedef struct {
    uint16_t forward;
    bool aim, sensitivity, calibrate;
} ButtonActions;

/* AIM is a modifier: hold it first, then tap a function key. After a chord,
 * release all keys before pointing again. A plain button still fires on press. */
static inline ButtonActions buttonActions(uint16_t previous, uint16_t held, bool *chord)
{
    const uint16_t aim = 1u << KEY_AIM_INDEX;
    const uint16_t others = held & ~aim;
    const uint16_t rising = held & ~previous;
    ButtonActions a = {0};
    if (!held) *chord = false;
    if (held & aim) {
        if (others) *chord = true;
        a.aim = !*chord;
        a.sensitivity = others == (1u << KEY_OK_INDEX) && (rising & others);
        a.calibrate = others == (1u << KEY_HOME_INDEX) && (rising & others);
    } else if (!*chord) {
        a.forward = rising;
    }
    return a;
}
