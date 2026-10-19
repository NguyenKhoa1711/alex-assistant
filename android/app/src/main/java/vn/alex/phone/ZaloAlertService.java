package vn.alex.phone;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.graphics.Rect;
import android.graphics.Path;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import java.util.ArrayList;
import java.util.List;

/** A bounded, user-started UI workflow. Does nothing while idle or outside Zalo. */
public final class ZaloAlertService extends AccessibilityService {
    private static final String PKG = "com.zing.zalo";
    private static final int NOTIFICATION = 830;
    private static ZaloAlertService instance;
    private static String previewResult = "";
    private static int previewReadyPerson = -1;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private AlertStore store;
    private String run = "";
    private AlertPlan plan;
    private boolean active, dry, dryMessageChecked;
    private int person, personIndex, state;
    private long stateAt, nextPoll, started;
    private String expectedName;
    private String lastDiagnostic = "";
    private static final int SEARCH = 0, CHOOSE = 1, CHAT = 2, ATTACH = 3,
            LIVE = 4, DURATION = 5, RETURN_CHAT = 6, WRITE = 7, SEND = 8, SENT = 9;
    private final Runnable poll = new Runnable() {
        @Override public void run() {
            if (!active) return;
            try { step(); } catch (Exception e) { fail("Thao tác Zalo bị gián đoạn; không tự gửi lại."); }
            handler.removeCallbacks(this);
            if (active) handler.postDelayed(this, 350);
        }
    };
    static boolean available() { return instance != null; }
    static boolean busy() { return instance != null && instance.active; }
    static String previewStatus() { return previewResult; }
    static int previewReadyPerson() { return previewReadyPerson; }
    static void clearPreviewReady() { previewReadyPerson = -1; }
    static void cancel() {
        if (instance != null && instance.active) instance.abort("Đã dừng thao tác; tin / hành trình đã gửi không bị thu hồi.");
    }
    static boolean preview(Context context, int person, int level) {
        if (instance == null || instance.active) return false;
        instance.dry = true;
        instance.person = person;
        instance.run = "";
        instance.plan = new AlertPlan(level);
        previewResult = "Đang tìm " + instance.store.name(person) + "; không gửi gì.";
        previewReadyPerson = -1;
        instance.beginPerson();
        return true;
    }
    static boolean start(Context context, String run, AlertPlan plan) {
        if (instance == null || instance.active) return false;
        instance.dry = false;
        instance.run = run;
        instance.plan = plan;
        instance.personIndex = 0;
        instance.person = plan.recipients[0];
        instance.beginPerson();
        return true;
    }
    @Override protected void onServiceConnected() { instance = this; store = new AlertStore(this); }
    @Override public void onAccessibilityEvent(AccessibilityEvent event) { /* Poll only during an explicit job. */ }
    @Override public void onInterrupt() { cancel(); }
    @Override public void onDestroy() { cancel(); instance = null; handler.removeCallbacksAndMessages(null); super.onDestroy(); }

    private void beginPerson() {
        active = true;
        dryMessageChecked = false;
        expectedName = store.name(person);
        started = SystemClock.elapsedRealtime();
        transition(SEARCH);
        tell("Tìm " + expectedName + " trong Zalo" + (dry ? " • thử, không gửi" : ""));
        try {
            // This is Zalo's installed Search shortcut intent, observed on the OPPO.
            startActivity(new Intent("com.zing.zalo.action.SHORTCUT_GLOBAL_SEARCH")
                    .setClassName(PKG, "com.zing.zalo.ui.IntentHandlerActivityAlias")
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP));
        } catch (Exception ex) { fail("Không mở được tìm kiếm Zalo. Mở Zalo và thử lại."); return; }
        handler.removeCallbacks(poll);
        handler.postDelayed(poll, 700);
    }
    private void transition(int value) {
        state = value; stateAt = SystemClock.elapsedRealtime(); nextPoll = stateAt + 700;
        android.util.Log.d("AlexAlerts", "mode=" + (dry ? "preview" : "alert") + " step=" + value);
    }
    private void step() {
        long now = SystemClock.elapsedRealtime();
        if (now < nextPoll) return;
        if (!dry && !store.isRun(run)) { abort("Phiên đã kết thúc. Không tiếp tục gửi."); return; }
        if (now - started > 150000 || now - stateAt > 35000) {
            fail("Zalo chưa hoàn tất bước hiện tại. Đã dừng, không tự gửi lại."); return;
        }
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return;
        try {
            if (!PKG.contentEquals(root.getPackageName() == null ? "" : root.getPackageName())) return;
            AccessibilityNodeInfo title = byId(root, "actionbar_txtTitle");
            boolean correctChat = title != null && same(title.getText(), expectedName) && byId(root, "chatinput_text") != null;
            if (dry) {
                String diagnostic = "step=" + state + " title=" + (title != null)
                        + " match=" + (title != null && same(title.getText(), expectedName))
                        + " edit=" + (byId(root, "chatinput_text") != null)
                        + " attach=" + (byId(root, "new_chat_input_btn_attach") != null);
                if (!diagnostic.equals(lastDiagnostic)) {
                    android.util.Log.d("AlexAlerts", diagnostic); lastDiagnostic = diagnostic;
                }
            }
            if (state != SEARCH && state != CHOOSE && byId(root, "chatinput_text") != null && !correctChat) {
                fail("Tên cuộc trò chuyện không khớp " + expectedName + ". Không gửi."); return;
            }
            switch (state) {
                case SEARCH: {
                    AccessibilityNodeInfo search = byId(root, "searchEditTxt");
                    if (search != null && setText(search, expectedName)) transition(CHOOSE);
                    break;
                }
                case CHOOSE: {
                    if (correctChat) { transition(CHAT); break; }
                    AccessibilityNodeInfo search = byId(root, "searchEditTxt");
                    if (search == null || !same(search.getText(), expectedName)) break;
                    List<AccessibilityNodeInfo> candidates = contacts(root, expectedName);
                    if (candidates.size() > 1) { fail("Có nhiều người trùng tên. Hãy đặt tên gợi nhớ riêng trong Zalo trước."); break; }
                    if (candidates.size() == 1) {
                        if (clickContact(candidates.get(0))) transition(CHAT);
                    } else if (now - stateAt > 3000) {
                        tell("Zalo chưa cung cấp tên kết quả. Chạm đúng " + expectedName + " để tiếp tục; Alex sẽ kiểm tra lại tên.");
                    }
                    break;
                }
                case CHAT: {
                    if (!correctChat) break;
                    boolean gps = getSystemService(android.location.LocationManager.class).isLocationEnabled();
                    int next = AlertRoute.next(plan, dry ? dryMessageChecked : store.claimed(run, messageOp()),
                            !dry && store.claimed(run, "location" + person), gps);
                    if (next == AlertRoute.MESSAGE) { tell("Đang kiểm tra ô gửi tin cấp " + plan.level); transition(WRITE); }
                    else if (next == AlertRoute.LOCATION) {
                        if (click(byId(root, "new_chat_input_btn_attach"))) { tell("Đang mở chia sẻ hành trình 8 giờ"); transition(ATTACH); }
                    } else if (dry) fail("Vị trí đang tắt; đã kiểm tra ô gửi nhưng chưa kiểm tra được hành trình.");
                    else donePerson(gps ? "Đã xử lý các bước được yêu cầu; xem kết quả từng kênh"
                            : "Vị trí đang tắt, chưa chia sẻ hành trình. Xem kết quả tin nhắn riêng.");
                    break;
                }
                case ATTACH:
                    if (!correctChat) break;
                    if (click(exact(root, "Vị trí"))) transition(LIVE);
                    break;
                case LIVE:
                    if (click(byId(root, "live_location_bar_tv_title"))) transition(DURATION);
                    break;
                case DURATION: {
                    AccessibilityNodeInfo duration = exact(root, "Trong 8 giờ");
                    AccessibilityNodeInfo heading = exact(root, "Chia sẻ hành trình của bạn trong:");
                    if (duration == null || heading == null) break;
                    if (dry) {
                        previewReadyPerson = person;
                        previewResult = "Thử cấp " + plan.level + ": đã tìm " + expectedName
                                + (dryMessageChecked ? ", ô soạn tin" : "")
                                + " và lựa chọn 8 giờ. Không nhập hay gửi tin, không chia sẻ vị trí. Trở lại Alex để xác nhận đúng người.";
                        active = false;
                        tell(previewResult);
                    } else {
                        if (!store.claim(run, "location" + person)) { fail("Hành trình đã được xử lý; không tự gửi lại."); break; }
                        store.status(run, "location" + person, "Đã yêu cầu chia sẻ 8 giờ; cần kiểm tra thẻ hành trình trong Zalo");
                        if (!click(duration)) { fail("Không bấm được lựa chọn 8 giờ."); break; }
                        transition(RETURN_CHAT);
                    }
                    break;
                }
                case RETURN_CHAT:
                    if (correctChat) {
                        // Only report active when Zalo exposes an explicit stop-sharing control.
                        if (exact(root, "Dừng chia sẻ") != null) {
                            store.status(run, "location" + person, "Zalo đang chia sẻ hành trình; đã chọn thời hạn 8 giờ");
                            store.shared(person);
                        }
                        donePerson("Đã thực hiện các bước; xem riêng trạng thái hành trình và tin nhắn");
                    }
                    break;
                case WRITE: {
                    if (!correctChat) break;
                    if (dry) {
                        // Never write a draft, click Send, claim a job, or invoke SMS in preview.
                        if (byId(root, "chatinput_text") == null) break;
                        dryMessageChecked = true;
                        transition(CHAT); break;
                    }
                    String op = messageOp();
                    AccessibilityNodeInfo edit = byId(root, "chatinput_text");
                    String draft = String.valueOf(edit.getText() == null ? "" : edit.getText());
                    if (!edit.isShowingHintText() && !draft.isEmpty()) {
                        fail("Cuộc trò chuyện có bản nháp. Alex không ghi đè hoặc gửi bản nháp đó."); break;
                    }
                    if (!store.claim(run, op)) { donePerson("Nội dung cấp này đã xử lý; không tự gửi lặp"); break; }
                    if (setText(edit, plan.message)) transition(SEND);
                    else fail("Không nhập được nội dung vào Zalo.");
                    break;
                }
                case SEND: {
                    AccessibilityNodeInfo edit = byId(root, "chatinput_text");
                    if (!correctChat || edit == null || !plan.message.contentEquals(edit.getText() == null ? "" : edit.getText())) {
                        fail("Tên hoặc nội dung trước gửi không khớp. Không gửi."); break;
                    }
                    if (click(byId(root, "new_chat_input_btn_chat_send"))) {
                        store.status(run, messageOp(), "Đã bấm gửi; đang chờ Zalo xóa ô soạn tin"); transition(SENT);
                    }
                    else fail("Không tìm thấy nút gửi của Zalo.");
                    break;
                }
                case SENT: {
                    AccessibilityNodeInfo edit = byId(root, "chatinput_text");
                    if (correctChat && edit != null && (edit.isShowingHintText() || edit.getText() == null
                            || edit.getText().length() == 0)) {
                        store.status(run, messageOp(), "Đã chuyển tin vào Zalo; chưa xác nhận người nhận đã nhận/đọc");
                        transition(CHAT);
                    }
                    break;
                }
                default: fail("Trạng thái không hợp lệ, đã dừng.");
            }
        } finally { root.recycle(); }
    }
    private String messageOp() { return "message" + plan.level + ":" + person; }
    private void donePerson(String message) {
        store.status(run, "zalo" + person, message);
        personIndex++;
        if (personIndex < plan.recipients.length) {
            person = plan.recipients[personIndex];
            beginPerson();
        } else { active = false; tell("Đã xử lý cảnh báo. Mở Alex xem kết quả từng kênh."); }
    }
    private void fail(String message) {
        if (!dry && plan != null && personIndex + 1 < plan.recipients.length && store.isRun(run)) {
            // One contact failing must not suppress an attempt to the other contact.
            store.status(run, "zalo" + person, message);
            person = plan.recipients[++personIndex];
            beginPerson();
            return;
        }
        abort(message);
    }
    private void abort(String message) {
        if (dry) previewResult = message + " Chế độ thử không gửi gì.";
        else {
            store.status(run, "zalo" + person, message);
            if (plan != null) for (int i = personIndex + 1; i < plan.recipients.length; i++)
                store.status(run, "zalo" + plan.recipients[i], "Chưa thực hiện vì thao tác Zalo đã dừng. SMS có trạng thái riêng.");
        }
        active = false;
        handler.removeCallbacks(poll);
        tell(message);
    }
    private void tell(String message) {
        if (dry && active) previewResult = message;
        if (!dry && active) store.status(run, "zalo" + person, message);
        NotificationManager manager = getSystemService(NotificationManager.class);
        NotificationChannel channel = new NotificationChannel("alex-alerts-quiet", "Tiến trình Alex (im lặng)", NotificationManager.IMPORTANCE_LOW);
        channel.setSound(null, null); channel.enableVibration(false);
        manager.createNotificationChannel(channel);
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, AlertActivity.class), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent stop = PendingIntent.getBroadcast(this, 0, new Intent(this, AlertCancelReceiver.class), PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder notification = new Notification.Builder(this, "alex-alerts-quiet")
                .setSmallIcon(android.R.drawable.ic_dialog_alert).setContentTitle(dry ? "Alex • thử, không gửi" : "Cảnh báo Alex")
                .setContentText(message).setStyle(new Notification.BigTextStyle().bigText(message))
                .setContentIntent(open).setOngoing(active).setAutoCancel(!active).setOnlyAlertOnce(true)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .setPublicVersion(new Notification.Builder(this, "alex-alerts-quiet")
                        .setSmallIcon(android.R.drawable.ic_dialog_alert).setContentTitle("Alex")
                        .setContentText("Mở ứng dụng để xem tiến trình").build());
        if (active) notification.addAction(new Notification.Action.Builder(null, "Dừng thao tác", stop).build());
        manager.notify(NOTIFICATION, notification.build());
    }
    private static boolean same(CharSequence actual, String expected) {
        return actual != null && AlertPlan.contactKey(actual.toString()).equals(AlertPlan.contactKey(expected));
    }
    private static AccessibilityNodeInfo byId(AccessibilityNodeInfo root, String id) {
        List<AccessibilityNodeInfo> nodes = root.findAccessibilityNodeInfosByViewId(PKG + ":id/" + id);
        for (AccessibilityNodeInfo n : nodes) if (n.isVisibleToUser()) return n;
        return null;
    }
    private static AccessibilityNodeInfo exact(AccessibilityNodeInfo root, String value) {
        if (root.isVisibleToUser() && (same(root.getText(), value) || same(root.getContentDescription(), value))) return root;
        for (int i = 0; i < root.getChildCount(); i++) {
            AccessibilityNodeInfo child = root.getChild(i);
            if (child != null) { AccessibilityNodeInfo found = exact(child, value); if (found != null) return found; }
        }
        return null;
    }
    private static List<AccessibilityNodeInfo> contacts(AccessibilityNodeInfo root, String name) {
        List<AccessibilityNodeInfo> result = new ArrayList<>();
        AccessibilityNodeInfo label = exact(root, "Liên hệ");
        if (label == null) return result;
        Rect section = new Rect(); label.getBoundsInScreen(section);
        AccessibilityNodeInfo messages = exact(root, "Tin nhắn");
        Rect end = new Rect(); if (messages != null) messages.getBoundsInScreen(end);
        collectContacts(root, name, section.bottom, messages == null ? Integer.MAX_VALUE : end.top, result);
        return result;
    }
    private static void collectContacts(AccessibilityNodeInfo node, String name, int top, int bottom, List<AccessibilityNodeInfo> out) {
        Rect bounds = new Rect(); node.getBoundsInScreen(bounds);
        if (node.isVisibleToUser() && bounds.top >= top && bounds.bottom <= bottom && same(node.getText(), name)) {
            out.add(node); return;
        }
        for (int i = 0; i < node.getChildCount(); i++) { AccessibilityNodeInfo child = node.getChild(i); if (child != null) collectContacts(child, name, top, bottom, out); }
    }
    private static boolean click(AccessibilityNodeInfo node) {
        int parents = 0;
        while (node != null && parents++ < 4) {
            if (node.isVisibleToUser() && node.isEnabled() && node.isClickable()) return node.performAction(AccessibilityNodeInfo.ACTION_CLICK);
            node = node.getParent();
        }
        return false;
    }
    private boolean clickContact(AccessibilityNodeInfo node) {
        if (click(node)) return true;
        // Zalo exposes the exact row text but no ACTION_CLICK on this OPPO.
        // Tap only the unique matched row, then validate the chat title again.
        Rect bounds = new Rect(); node.getBoundsInScreen(bounds);
        if (!node.isVisibleToUser() || !same(node.getText(), expectedName)
                || bounds.width() <= 0 || bounds.height() <= 0) return false;
        Path path = new Path(); path.moveTo(bounds.centerX(), bounds.centerY());
        return dispatchGesture(new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, 70)).build(), null, handler);
    }
    private static boolean setText(AccessibilityNodeInfo node, String text) {
        Bundle args = new Bundle(); args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        return node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
    }
}
