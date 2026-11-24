# C3 handheld PCB reference — Rev C, 23 November 2026

Use `01-power-usb.svg` and `02-controller-inputs.svg` to draw the Fusion schematic; PNG copies are included. These are electrical reference drawings, not fabrication files. GPIOs match the current C3 matrix firmware. No firmware changes or hardware measurements were made for this revision.

**Module:** solder-down ESP32-C3-MINI-1, using the Espressif land pattern. This is not a SuperMini development-board footprint. The receiver uses a separate UART wiring profile.

## Fit and reserve

| Parts | First assembly | Purpose / footprint |
|---|---|---|
| R11–R13 | **Fit 10 kΩ**, one per row | External pull-ups, 0603; establish released/wake levels independently of internal pulls |
| D1–D9 | **Fit 1N4148W**, SOD123 | Anode toward row/switch; band/cathode toward column |
| C13–C15 | **DNP** | Row-to-GND filter positions, 0603; large values can produce false matrix keys |
| R20–R22 | **Fit 0 Ω**, 0603 | GPIO6/7/10 → COL1/2/3; isolation/rework links |
| R17 | **Fit 0 Ω**, 1206, rated ≥2 A | BAT_PROT → BAT_SYS; remove and bridge with an ammeter for battery-current measurement |
| R18 / R19 | **Fit R18 = 0 Ω; DNP R19** | BAT_SYS → BOOST_EN; optional 100 kΩ EN pulldown for future rework. Remove R18 before driving EN externally |
| C16 / C17 | **DNP**, 1206 | Extra ceramic capacitance at MCU supply / boost input |
| C18 / C19 | **DNP**, 0603 | USB D+/D− shunt-capacitor positions; values require signal testing |
| D11 / D12 | **DNP**, SOD323 | Reserve PESD3V3U1UA ESD parts at USB header: pin 1 cathode to data, pin 2 anode to GND. Prefer fitting for field handling |
| R15 / R16 | **DNP if breakout has pull-ups**, otherwise fit 4.7 kΩ | SDA/SCL → SYS_3V3; 0603 |
| R23 | **Fit 0 Ω**, 0603 | SYS_3V3 → V_MPU; supply measurement/rework link, not a firmware power switch |
| C12 / C20 | **Fit C12 = 100 nF; DNP C20 = 1 µF**, 0603 | V_MPU → GND, close to header |
| JP1 | **Bridge 1–2** for battery operation | 1 VBOOST, 2 SYS_3V3, 3 fixture 3.3 V. Never bridge both sides |
| JP2 | **Bridge 2–3** for address 0x69 | 1 GND, 2 MPU_AD0, 3 V_MPU. Alternative 1–2 gives 0x68; firmware accepts either |

All other parts shown are fitted. Use 1% resistors for R1–R4. R1/R2 = **100 kΩ / 22 kΩ**. Fit **C5, C6 and C7 = 1 nF each** as drawn: C5 in parallel with the series pair C6+C7 gives 1.5 nF. Alternatively fit only C5 = 1.5 nF and leave C6/C7 empty; do not mix the two assembly choices.

## Power and programming

- Two AAA **alkaline** cells in series; no charger. BT1 may use battery-holder wire pads until the exact holder is selected. Mark polarity clearly and provide wire strain relief.
- Q1 **DMP2035U-7**, SOT23: gate 1 → GND, source 2 → BAT_PROT, drain 3 → BAT_RAW. R17 feeds both the converter and ADC divider, so its measurement includes those loads.
- U1 **TPS61023DRLR**, TI DRL/SOT563: 1 FB, 2 EN, 3 VIN, 4 GND, 5 SW, 6 VOUT. It is a **boost** converter. EN is normally high through R18; this design has no hardware 2 V cutoff. Low-battery warning/lockout is not yet implemented in firmware.
- L1 **SWPA6045S1R0NT, 1 µH**. Use the Sunlord land pattern; body is 6.0 ±0.3 mm square, 4.5 mm maximum height. Include its height in enclosure clearance.
- C1/C2 = 10 µF, C3/C4/C9 = 22 µF: allow 1206, X5R/X7R, preferably 10 V. Check the exact capacitor's effective capacitance at operating voltage. C10/C12 = 100 nF; C11 = 1 µF; C8 = 100 nF. Small capacitors may use 0603 with ≥6.3 V rating. C5–C7: preferably C0G/NP0, 0603.
- ADC measures BAT_SYS / 2 through R3/R4 = 100 kΩ / 100 kΩ. Do not change the ratio without updating firmware. It measures the protected, loaded battery rail; compare it with a meter on the first board.
- J1 order: **D+, D−, regulated 3.3 V, GND**. Pin 3 is **not USB VBUS**. An ordinary USB cable supplies 5 V; use an external 3.3 V fixture rated ≥500 mA, or power from batteries and leave J1 pin 3 unused. JP1 isolates the two positive supplies. Move its bridge only with power removed.
- Keep BOOT and RESET service switches/pads accessible beneath the battery cover. Hold BOOT and pulse RESET for recovery. Tactile-switch footprints must join the correct two independent contacts.

## Layout points before ordering

1. Place U1, L1, C1–C4 and feedback parts together; keep the switching loop short and FB away from SW. Ground capacitors directly into the local ground plane. Follow TI's reference layout rather than routing these parts wherever space remains.
2. Put C9/C10 beside U2's 3.3 V supply. Use short, wide supply/ground paths; allow ≥500 mA output capability and higher battery-side pulse current. A meter reading alone cannot confirm transient stability.
3. Place the module antenna at the PCB edge, preferably overhanging it. Follow Espressif's antenna keepout; if overhang is impossible, maintain the specified clearance (at least 15 mm around the antenna) without copper, traces or components. Keep batteries and metal out of that region.
4. Route USB as a short matched differential pair over continuous GND (90 Ω differential target). R5/R6 and optional C18/C19 go near U2; ESD pads go near J1. Do not add long test-point stubs to USB.
5. J2 numbers are a proposed connector definition, **not proof of the actual MPU module footprint**. Match VCC/GND/SCL/SDA/XDA/XCL/AD0/INT to its silkscreen, confirm header orientation and edge offset, and preserve the tested IMU orientation. The stated module envelope is 21 × 16 mm, with a 1×8 2.54 mm header. Check the breakout's regulator and power LED; they affect sleep current. Removing R23 alone may allow I2C back-powering; isolate signal connections as well for an unpowered-module test.
6. Add exposed, labelled test pads: TP1–3 rows; TP4–6 columns; TP7 SYS_3V3; TP8 GND; TP9 BAT_RAW; TP10 BAT_PROT; TP11 BAT_SYS; TP12 VBOOST; TP13 BOOST_EN; TP14 BAT_ADC; TP15 FIX_3V3; TP16 GND; TP17 EN_RESET; TP18 BOOT9; TP19 MPU_SDA; TP20 MPU_SCL. Use approximately 1.5 mm pads where space permits, with nearby GND access.

**Before fabrication:** review the actual Fusion schematic/ERC, footprints and PCB layout. **Before assembling the whole batch:** validate one board's supply under radio/AIM load, wake/first-press delivery, ADC reading and sleep current. The regulator circuit is datasheet-based but is not yet hardware-qualified; extra footprints provide rework options, not a guarantee.

## Source references

- [TI TPS61023 datasheet — pinout, compensation and layout](https://www.ti.com/lit/ds/symlink/tps61023.pdf)
- [Espressif MINI-1 module — pad mapping and land pattern](https://documentation.espressif.com/esp32-c3-mini-1_datasheet_en.pdf)
- [Espressif schematic guidance — reset, supply and USB](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32c3/schematic-checklist.html)
- [Espressif PCB guidance — module antenna and USB routing](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32c3/pcb-layout-design.html)
- [Sunlord SWPA series — dimensions and current ratings](https://www.sunlordinc.com/uploads/files/20221122/SWPA%20series%20of%20SMD%20Power%20Inductor.pdf)
- [Diodes DMP2035U — package and electrical ratings](https://www.diodes.com/datasheet/download/DMP2035U.pdf)
- [Nexperia PESD3V3U1UA — ESD part and pin assignment](https://assets.nexperia.com/documents/data-sheet/PESD3V3U1UA.pdf)
- [Diodes 1N4148W — SOD123 switching diode](https://www.diodes.com/part/view/1N4148W)
