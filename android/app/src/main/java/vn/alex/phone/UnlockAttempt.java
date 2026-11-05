package vn.alex.phone;

import java.util.Arrays;
import java.util.concurrent.atomic.AtomicBoolean;

/** One credential confirmation, never reused by a later attempt. No Android state is persisted. */
final class UnlockAttempt {
    static final long AUTH_TIMEOUT_MS = 60000;
    final int requestCode;
    final AtomicBoolean cancelled = new AtomicBoolean();
    private final long startedAt;
    private byte[] pending;
    private boolean claimed, expired;

    // Takes ownership of digits; the caller must not retain or use this buffer.
    UnlockAttempt(int requestCode, byte[] digits, long now) {
        this.requestCode = requestCode;
        this.startedAt = now;
        this.pending = digits;
    }

    static boolean canStart(boolean paired, String laptopStatus, boolean busy) {
        return paired && !busy && "locked".equals(laptopStatus);
    }

    synchronized boolean expire(long now) {
        if (claimed || cancelled.get()) return expired;
        // elapsedRealtime includes device sleep; Handler's delayed callback alone does not.
        if (now < startedAt || now - startedAt >= AUTH_TIMEOUT_MS) {
            expired = true;
            cancel();
        }
        return expired;
    }

    synchronized byte[] confirm(boolean accepted, long now) {
        if (claimed || cancelled.get()) return null;
        if (!accepted || expire(now)) { cancel(); return null; }
        claimed = true;
        byte[] digits = pending;
        pending = null;
        return digits; // Worker owns and wipes this buffer from now on.
    }

    synchronized boolean wasClaimed() { return claimed; }
    synchronized boolean isExpired() { return expired; }

    synchronized void cancel() {
        cancelled.set(true);
        if (pending != null) { Arrays.fill(pending, (byte)0); pending = null; }
    }
}
