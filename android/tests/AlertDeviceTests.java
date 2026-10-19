package vn.alex.phone;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.os.Bundle;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;

/** Separate test APK. Uses an isolated preferences file and never invokes a sender. */
public final class AlertDeviceTests extends Instrumentation {
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        Context context = getTargetContext();
        String namespace = "alert_test_" + UUID.randomUUID().toString();
        Bundle result = new Bundle();
        try {
            check(!context.getSystemService(android.app.KeyguardManager.class).isKeyguardLocked(), "unlock phone before UI tests");
            AlertPolicyTests.run();
            AlertStore store = new AlertStore(context, namespace);
            store.save(new String[]{"Người thân 1", "Người thân 2"}, new String[]{"0900000001", "0900000002"}, 1);
            check(store.phone(0).equals("0900000001"), "encrypted contact round trip");
            String serialized = context.getSharedPreferences(namespace, Context.MODE_PRIVATE).getString("phone0", "");
            check(!serialized.contains("0900000001"), "no plaintext contact stored");
            String run = store.begin(1);
            check(!run.isEmpty(), "begin level1");
            check(store.begin(1).isEmpty(), "repeat level blocked");
            store.status(run, "zalo0", "Searching contact");
            check(!store.claimed(run, "location0"), "searching is not a shared journey");
            check(store.claim(run, "location0"), "first claim");
            check(store.claimed(run, "location0"), "journey dispatch is durably marked");
            AlertStore reopened = new AlertStore(context, namespace);
            check(!reopened.claim(run, "location0"), "no resend after process recreation");
            check(reopened.begin(2).equals(run), "upgrade reuses session");
            check(reopened.hasPendingZalo(new AlertPlan(2)), "level2 can continue unsent call text after level1");
            check(reopened.claim(run, "message2:0"), "level2 text claim is independent of journey");
            check(!reopened.hasPendingZalo(new AlertPlan(2)), "finished level2 cannot blindly resend");
            check(reopened.begin(3).equals(run), "level3 upgrade");
            check(!reopened.claim(run, "location0"), "upgrade does not restart journey");
            AtomicInteger claims = new AtomicInteger();
            CountDownLatch done = new CountDownLatch(8);
            for (int i = 0; i < 8; i++) new Thread(() -> {
                if (new AlertStore(context, namespace).claim(run, "sms0")) claims.incrementAndGet();
                done.countDown();
            }).start();
            done.await();
            check(claims.get() == 1, "concurrent double tap dispatches once");
            store.smsPart(run, "sms0", 2, 3, true);
            check(!store.status("sms0").startsWith("Đã gửi qua SIM"), "partial SMS not complete");
            store.smsPart(run, "sms0", 0, 3, true);
            store.smsPart(run, "sms0", 2, 3, true);
            check(!store.status("sms0").startsWith("Đã gửi qua SIM"), "duplicate callback not counted twice");
            store.smsPart(run, "sms0", 1, 3, true);
            check(store.status("sms0").startsWith("Đã gửi qua SIM"), "all parts accepted");
            check(store.claim(run, "sms1"), "other contact independent");
            store.smsPart(run, "sms1", 0, 2, false);
            store.smsPart(run, "sms1", 1, 2, true);
            check(store.status("sms1").contains("SMS lỗi"), "partial failure stays failure");
            check(!store.claim(run, "sms1"), "failure does not silently retry");
            boolean frozen = false;
            try { store.save(new String[]{"X", "Y"}, new String[]{"", ""}, 2); } catch (IllegalStateException e) { frozen = true; }
            check(frozen, "recipients frozen during alert");
            store.end();
            String next = store.begin(3);
            check(!next.equals(run), "explicit new session");
            store.smsPart(run, "sms0", 0, 1, true);
            check(store.status("sms0").equals("Chưa thực hiện"), "late callback cannot mutate new run");
            // Read only setup booleans; never print a phone number or pairing credential.
            AlertStore actual = new AlertStore(context);
            String phone0 = AlertPlan.canonicalPhone(actual.phone(0));
            String phone1 = AlertPlan.canonicalPhone(actual.phone(1));
            result.putBoolean("setup_two_valid_numbers", !phone0.isEmpty() && !phone1.isEmpty() && !phone0.equals(phone1));
            result.putBoolean("setup_contacts_verified", actual.verified(0) && actual.verified(1));
            result.putBoolean("setup_active_sim", AlertSms.hasSim(context, actual.sim()));
            result.putBoolean("setup_sms_permission", context.checkSelfPermission(android.Manifest.permission.SEND_SMS)
                    == android.content.pm.PackageManager.PERMISSION_GRANTED);
            result.putBoolean("setup_location_enabled", context.getSystemService(android.location.LocationManager.class).isLocationEnabled());
            result.putInt("actual_alert_level", actual.level());
            result.putString("actual_zalo_state", actual.status("zalo0"));
            result.putString("actual_level2_message_state", actual.status("message2:0"));
            result.putBoolean("setup_quiet_permission", new AlertQuiet(context).permitted());
            testHoldWidget(context);
            result.putString("stream", "PASS " + AlertPolicyTests.checks + " checks. No SMS, Zalo messages, or locations sent.\n");
            finish(Activity.RESULT_OK, result);
        } catch (Throwable e) {
            result.putString("stream", "FAIL " + e.getClass().getSimpleName() + ": " + e.getMessage() + "\n");
            finish(Activity.RESULT_CANCELED, result);
        } finally { context.deleteSharedPreferences(namespace); }
    }
    private static void check(boolean value, String message) { AlertPolicyTests.check(value, message); }
    private void testHoldWidget(Context context) {
        android.content.Intent intent = new android.content.Intent(context, AlertActivity.class)
                .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
        Activity activity = startActivitySync(intent);
        AtomicInteger count = new AtomicInteger();
        HoldButton[] button = new HoldButton[1];
        runOnMainSync(() -> {
            activity.getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            button[0] = new HoldButton(activity, "THỬ NÚT • KHÔNG GỬI", 0xff956414, count::incrementAndGet);
            activity.setContentView(button[0]);
        });
        waitForIdleSync();
        boolean[] focused = {false};
        for (int i = 0; i < 20 && !focused[0]; i++) {
            runOnMainSync(() -> focused[0] = button[0].hasWindowFocus());
            android.os.SystemClock.sleep(100);
        }
        check(focused[0], "hold test window must be foreground and unlocked");
        touch(button[0], android.view.MotionEvent.ACTION_DOWN);
        android.os.SystemClock.sleep(700);
        touch(button[0], android.view.MotionEvent.ACTION_UP);
        check(count.get() == 0, "short real button press cannot send");
        touch(button[0], android.view.MotionEvent.ACTION_DOWN);
        android.os.SystemClock.sleep(3400);
        check(count.get() == 1, "actual Android hold callback fires after 3 seconds");
        android.os.SystemClock.sleep(800);
        touch(button[0], android.view.MotionEvent.ACTION_UP);
        check(count.get() == 1, "release after activation does not duplicate");
        runOnMainSync(activity::finish);
    }
    private void touch(HoldButton button, int action) {
        runOnMainSync(() -> {
            long now = android.os.SystemClock.uptimeMillis();
            android.view.MotionEvent event = android.view.MotionEvent.obtain(now, now, action, 20, 20, 0);
            button.onTouchEvent(event); event.recycle();
        });
    }
}
