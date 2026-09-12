# tools/archive - checkers for layouts that are no longer on the glass

These are kept because each one documents how a past layout was proved, and
because the reasoning in their header blocks is still worth reading. None of
them describes v14.0, and none of them is run by anything.

| script | proved, for | why it was retired |
|---|---|---|
| `verify_gate_window.py` | v7.0's per-minute window (gates 101..237, clock at x=50) | v14.0 derives its window from `epd_layout.h`. This script has its **own** copy of the old numbers, so after v14.0 it still printed `PASS` - while describing a window the firmware no longer writes. A check that passes on the wrong thing is worse than one that fails, so it had to go. |
| `verify_partial_window.py` | v6.0's IL0373-style rectangle, same x=50 clock | same as above, and its whole model of the window (a rectangle) is wrong for v14.0: SSD1680 windows are vertical bands, not rectangles. |
| `verify_ble_icon.py` | v11.0's 7x13 rune drawn at (233, 8) from `epd.c` | v14.0's rune is an 8x13 bitmap generated into `font_unifont.h` and drawn in row 3; `verify_v14_layout.py` covers it. |
| `verify_version_badge.py` | v10.0's right-aligned version badge at (199, 120) | v14.0 has no badge - the face has no room for one. The version is now checked by name (source, and the release file) instead. |
| `verify_refresh_debug.py` | v12.0/v13.0's H/T/B/L counters at `EPD_DEBUG_X/Y` | v14.0 draws the same counters in row 3 at `ROW3_X/Y`; the old X/Y constants are gone, so the script exits 1. Re-arming the counters is still supported (`EPD_USE_REFRESH_DEBUG 1`), and the property that mattered - that a *partial* refresh can never repaint a stale counter - is now asserted by `verify_v14_layout.py` ("the H/T/B/L counters sit clear of the per-minute band"). |

`verify_part_lut.py` and `verify_time_catchup.py` stayed in `tools/`: neither
depends on the face, and both still pass unchanged.
