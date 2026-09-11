#!/usr/bin/env python3
"""
Offline model of time.c:handler_time() - why the tag clock ran slow, and why the
'if' -> 'while' change fixes it.

Root cause being modelled
-------------------------
app.c drives main_loop() as:

    blt_sdk_main_loop();   <-- the BLE stack sleeps in here
    handler_time();        <-- evaluated ONCE per outer-loop iteration
    ...
    blt_pm_proc();         <-- only sets the suspend mask

Disassembly of the linked image shows blt_sdk_main_loop() (0x39b0..) next to
blt_brx_sleep() (0x3f28..0x4386), and blt_brx_sleep()'s literal pool contains
&cpu_sleep_wakeup (0x0084efb4).  So each outer iteration really does go to sleep
and only returns at the next BLE event.  With ADVERTISING_INTERVAL = 16000
(10 s, set by v5.0) that is roughly one handler_time() call per 10 s.

The old body

    if (clock_time() - last_clock_increase >= one_second_trimmed) {
        last_clock_increase += one_second_trimmed;
        current_unix_time++;
    }

advances the clock by at most ONE second per call, so the clock rate is clamped
to (calls per second) - which is far below 1.  The fix is to let it catch up:

    while (clock_time() - last_clock_increase >= one_second_trimmed) { ... }

clock_time() is safe to use as the real-time source: it is the 16 MHz system
timer (timer.h: "system Timer : 16Mhz, Constant"), and the SDK keeps it
continuous across sleep - main.c calls blc_pm_select_internal_32k_crystal(),
which sets pm_tim_recover = pm_tim_recover_32k_rc, and that routine was
disassembled as

    sys_tick = tick_cur + ((now_32k - last_32k) * tick_32k_calib) >> 4

i.e. a linear extrapolation of the 32k RTC, which does run while the MCU sleeps.

This script simulates both bodies against the same wake schedule and prints the
perceived clock rate.  It is a model, not a measurement.
"""

SEC_TICKS = 16_000_000 + 5_000      # one_second_trimmed = 16M + time_trime(5000)
ADV_INTERVAL_S = 10                 # v5.0: ADVERTISING_INTERVAL 16000 -> 10 s
WAKE_BURST_ITERS = 6                # main_loop() iterations per wake before sleeping again
SIM_SECONDS = 3600                  # one hour of real time


def simulate(catch_up_in_loop: bool, burst=WAKE_BURST_ITERS, adv=ADV_INTERVAL_S,
             seconds=SIM_SECONDS):
    """Return (counted_seconds, real_seconds, calls) for one simulated hour."""
    last_clock_increase = 0
    current_unix_time = 0
    calls = 0

    # the system timer is recovered by the SDK across every sleep, so clock_time()
    # is simply the real elapsed time expressed in 16 MHz ticks.
    def clock_time(real_elapsed_s):
        return int(real_elapsed_s * 16_000_000) & 0xFFFFFFFF

    real = 0.0
    last_eval = 0.0
    while real < seconds:
        # ---- one wake burst: the loop iterates a few times, then sleeps ----
        for _ in range(burst):
            calls += 1
            last_eval = real          # real time at the moment handler_time() runs
            now = clock_time(real)
            if catch_up_in_loop:
                while (now - last_clock_increase) & 0xFFFFFFFF >= SEC_TICKS:
                    last_clock_increase = (last_clock_increase + SEC_TICKS) & 0xFFFFFFFF
                    current_unix_time += 1
            else:
                if (now - last_clock_increase) & 0xFFFFFFFF >= SEC_TICKS:
                    last_clock_increase = (last_clock_increase + SEC_TICKS) & 0xFFFFFFFF
                    current_unix_time += 1
        real += adv  # sleep until the next advertising event

    # Compare against the real time at the LAST handler_time() call, not at the
    # end of the simulation: the clock can only know about time that has already
    # elapsed, and the final sleep interval has not finished when we stop.
    return current_unix_time, last_eval, calls


def main():
    ok = True

    old_s, real_s, calls_old = simulate(catch_up_in_loop=False)
    new_s, _, calls_new = simulate(catch_up_in_loop=True)

    print('simulated real time      : %.0f s (1 h), adv interval %d s, %d loop iters/wake'
          % (SIM_SECONDS, ADV_INTERVAL_S, WAKE_BURST_ITERS))
    print('main_loop calls / second : %.3f  (old=%d new=%d calls)'
          % (calls_old / real_s, calls_old, calls_new))
    print()
    print('OLD  if  : counted %5d s over %5.0f s real  -> clock rate %.3f  (%.1fx slow)'
          % (old_s, real_s, old_s / real_s, real_s / max(old_s, 1)))
    print('NEW  while: counted %5d s over %5.0f s real  -> clock rate %.3f'
          % (new_s, real_s, new_s / real_s))
    print()

    # 1) the old body must reproduce the reported symptom: a clock running
    #    clearly slower than real time (the user saw a tag minute take 2+ real
    #    minutes; the model says it is even worse than that).
    rate_old = old_s / real_s
    ok &= _check('old body runs slow (rate < 0.9)', rate_old < 0.9, '%.3f' % rate_old)

    # 2)+4) The new body must keep the clock within a fixed lag of real time: a
    #    clock legitimately shows the last COMPLETED second (<= 1 s behind), and
    #    one_second_trimmed carries time_trime = 5000, i.e. +312 ppm on top.
    #    What must never happen is an unbounded, growing lag.
    def lag_report(tag, counted, real):
        lag = real - counted
        rate = counted / real
        ok2 = -0.5 <= lag <= 2.0
        return _check('%-34s rate %.4f  lag %+.2f s' % (tag, rate, lag), ok2)

    ok &= lag_report('new body  adv=10  burst=6', new_s, real_s)
    for adv, burst in ((10, 6), (10, 1), (10, 200), (1, 1), (60, 3), (0.05, 4),
                       (200, 1), (10, 2)):
        s, r, _ = simulate(catch_up_in_loop=True, burst=burst, adv=adv, seconds=3600)
        ok &= lag_report('new body  adv=%-5s burst=%-4d' % (adv, burst), s, r)

    # 5) Known boundary, documented rather than hidden.  clock_time() is a 32-bit
    #    counter ticking at 16 MHz, so it wraps every 2^32/16e6 = 268.4 s.  A
    #    single sleep longer than that aliases the unsigned delta and the catch-up
    #    breaks.  This is not reachable in practice - the tag advertises every 10 s
    #    (ADVERTISING_INTERVAL 16000), so it can never sleep anywhere near 268 s -
    #    but it is the reason the fix is only valid while advertising stays on.
    s, r, _ = simulate(catch_up_in_loop=True, burst=1, adv=300, seconds=3600)
    lag = r - s
    ok &= _check('boundary: one sleep > 268 s (32-bit wrap) breaks catch-up, '
                 'unreachable with 10 s advertising', lag > 60, 'lag +%.0f s' % lag)

    # 3) the fix must not depend on the burst size: with a burst long enough that
    #    the loop runs more than once per second the OLD code was already correct,
    #    which is exactly why this bug only appeared after v5.0 stretched the
    #    advertising interval from 1 s to 10 s.
    old_dense, r_dense, _ = simulate(catch_up_in_loop=False, burst=20, adv=1)
    ok &= _check('old body was fine at adv=1 s / dense loop (rate ~1)',
                 abs(old_dense / r_dense - 1.0) < 0.01, '%.3f' % (old_dense / r_dense))

    print()
    print('RESULT:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


def _check(label, cond, detail=''):
    print('  [%s] %s %s' % ('ok' if cond else 'XX', label, detail))
    return bool(cond)


if __name__ == '__main__':
    raise SystemExit(main())
