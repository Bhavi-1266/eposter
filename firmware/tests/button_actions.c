#include "../main/buttons.h"

#define CHECK(test) do { if (!(test)) return __LINE__; } while (0)
int main(void)
{
    const uint16_t aim = 1u << KEY_AIM_INDEX, ok = 1u << KEY_OK_INDEX, home = 1u << KEY_HOME_INDEX;
    bool chord = false;
    CHECK(buttonActions(0, ok, &chord).forward == ok);
    CHECK(buttonActions(ok, ok, &chord).forward == 0);
    CHECK(buttonActions(0, aim, &chord).aim);
    ButtonActions a = buttonActions(aim, aim | ok, &chord);
    CHECK(a.sensitivity && !a.forward && !a.aim && !a.calibrate);
    CHECK(!buttonActions(aim | ok, aim | ok, &chord).sensitivity);
    CHECK(!buttonActions(aim | ok, aim, &chord).aim);
    CHECK(buttonActions(aim, aim | ok, &chord).sensitivity);
    CHECK(!buttonActions(aim | ok, ok, &chord).forward);
    buttonActions(ok, 0, &chord);
    CHECK(!chord);
    a = buttonActions(0, aim | home, &chord);
    CHECK(a.calibrate && !a.forward && !a.aim && !a.sensitivity);
    CHECK(!buttonActions(aim | home, aim | home, &chord).calibrate);
    a = buttonActions(aim | home, aim | home | ok, &chord);
    CHECK(!a.calibrate && !a.sensitivity && !a.aim && !a.forward);
    buttonActions(aim | home | ok, 0, &chord);
    CHECK(buttonActions(0, home, &chord).forward == home);
    CHECK(buttonActions(0, aim, &chord).aim);
    return 0;
}
