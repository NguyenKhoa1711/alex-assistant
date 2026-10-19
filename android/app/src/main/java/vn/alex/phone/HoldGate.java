package vn.alex.phone;

/** Clock is supplied so cancellation and long presses can be checked without a phone. */
final class HoldGate {
    private long start;
    private boolean armed;
    void down(long now) { start = now; armed = true; }
    void cancel() { armed = false; }
    boolean fire(long now) {
        if (!armed || now - start < AlertPlan.HOLD_MS) return false;
        armed = false;
        return true;
    }
}
