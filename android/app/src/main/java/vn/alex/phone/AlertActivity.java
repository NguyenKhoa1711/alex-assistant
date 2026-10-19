package vn.alex.phone;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.location.LocationManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.telephony.SubscriptionInfo;
import android.text.InputType;
import android.view.WindowManager;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.ArrayAdapter;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.List;

public final class AlertActivity extends Activity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final List<HoldButton> holds = new ArrayList<>();
    private final List<TextView> levelStatus = new ArrayList<>();
    private AlertStore store;
    private AlertQuiet quiet;
    private TextView results, readiness, quietStatus;
    private Button restoreAudio, stopAction, endAction;
    private final Runnable refresh = new Runnable() {
        @Override public void run() { refreshStatus(); handler.postDelayed(this, 800); }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        store=new AlertStore(this); quiet=new AlertQuiet(this);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout root=UiKit.column(this); root.setBackgroundColor(UiKit.BACKGROUND);
        UiKit.window(this,root); setContentView(root);
        LinearLayout toolbar=new LinearLayout(this);
        toolbar.setGravity(android.view.Gravity.CENTER_VERTICAL);
        TextView back=UiKit.text(this,"Cảnh báo an toàn",17,UiKit.INK,true);
        back.setCompoundDrawables(UiKit.icon(this,"back",UiKit.INK,24),null,null,null);
        back.setCompoundDrawablePadding(dp(12)); back.setPadding(dp(18),dp(18),dp(18),dp(18));
        back.setMinimumHeight(dp(60)); back.setContentDescription("Quay lại Alex, Cảnh báo an toàn");
        back.setBackground(UiKit.ripple(this,UiKit.BACKGROUND,false)); back.setOnClickListener(v -> finish());
        toolbar.addView(back,new LinearLayout.LayoutParams(0,-2,1));
        Button settings=UiKit.button(this,"Thiết lập",false,v -> setup());
        settings.setTextSize(13);
        LinearLayout.LayoutParams settingsParams=UiKit.space(this,-2,-2,0,0);
        settingsParams.rightMargin=dp(14); toolbar.addView(settings,settingsParams);
        root.addView(toolbar);
        ScrollView scroll=new ScrollView(this); scroll.setFillViewport(true);
        root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        LinearLayout content=UiKit.column(this); content.setPadding(dp(18),dp(6),dp(18),dp(28)); scroll.addView(content);
        content.addView(UiKit.text(this,getString(R.string.ui_alert_title),25,UiKit.INK,true));
        addText(content,getString(R.string.ui_alert_hint),14,UiKit.MUTED);
        readiness=addText(content,"",12,UiKit.MUTED);
        levelCard(content,1,"Đồng hành","Hành trình 8 giờ cho "+store.name(0)+".",UiKit.PRIMARY_DARK);
        levelCard(content,2,"Nhờ liên lạc","Hành trình 8 giờ và nhờ "+store.name(0)+" gọi lại qua Zalo.",UiKit.AMBER);
        levelCard(content,3,"Cầu cứu","Im lặng · Hành trình cho cả hai · Cầu cứu qua Zalo và SMS · Không gọi lại.",UiKit.DANGER);

        LinearLayout statusCard=UiKit.card(this); content.addView(statusCard,UiKit.space(this,-1,-2,18,16));
        statusCard.addView(UiKit.text(this,"Tiến trình cảnh báo",19,UiKit.INK,true));
        results=addText(statusCard,"Chưa có cảnh báo.",14,UiKit.INK);
        results.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        quietStatus=addText(statusCard,"",13,UiKit.MUTED);
        restoreAudio=UiKit.button(this,"Khôi phục âm thanh",false,v -> new AlertDialog.Builder(this)
                .setTitle("Bật lại âm thanh?").setMessage("Khôi phục âm lượng và chế độ chuông trước khi bật im lặng. Nhạc, chuông hoặc thông báo có thể phát lại.")
                .setNegativeButton("Giữ im lặng",null).setPositiveButton("Khôi phục",(d,w) -> {
                    boolean restored=quiet.restore(); refreshStatus();
                    if(!restored) message("Chưa khôi phục đủ thiết lập âm thanh. Kiểm tra quyền Không làm phiền rồi thử lại.");
                }).show());
        statusCard.addView(restoreAudio,UiKit.space(this,-1,-2,8,8));
        stopAction=UiKit.button(this,"Dừng thao tác đang chạy",false,v -> { ZaloAlertService.cancel(); refreshStatus(); });
        statusCard.addView(stopAction,UiKit.space(this,-1,-2,8,8));
        endAction=UiKit.button(this,"Kết thúc phiên cảnh báo",false,v -> new AlertDialog.Builder(this)
                .setTitle("Kết thúc phiên?")
                .setMessage("Dừng các thao tác còn lại và cho phép một phiên mới. Tin đã gửi không bị thu hồi. Hành trình đã chia sẻ cần dừng trong Zalo; hết 8 giờ Zalo sẽ tự dừng. Âm thanh vẫn im lặng đến khi bạn bấm Khôi phục.")
                .setNegativeButton("Quay lại",null).setPositiveButton("Kết thúc",(d,w) -> {
                    ZaloAlertService.cancel(); store.end(); refreshStatus();
                }).show());
        statusCard.addView(endAction);

        LinearLayout tools=UiKit.card(this);
        Button expand=UiKit.button(this,getString(R.string.ui_alert_tools),false,v -> {
            boolean open=tools.getVisibility()!=View.VISIBLE; tools.setVisibility(open ? View.VISIBLE : View.GONE);
            ((Button)v).setText(open ? "Thu gọn thiết lập và thử" : getString(R.string.ui_alert_tools));
        });
        content.addView(expand,UiKit.space(this,-1,-2,0,12)); content.addView(tools); tools.setVisibility(View.GONE);
        addText(tools,getString(R.string.ui_alert_tools_hint),14,UiKit.MUTED);
        tools.addView(UiKit.button(this,"Cấp quyền Không làm phiền",false,v -> quietSettings()),UiKit.space(this,-1,-2,0,10));
        tools.addView(UiKit.button(this,"Thử tìm người nhận · không gửi",false,v -> preview()),UiKit.space(this,-1,-2,0,10));
        tools.addView(UiKit.button(this,"Thử cấp 2 · không gửi",false,v -> testLevelTwo()),UiKit.space(this,-1,-2,0,10));
        tools.addView(UiKit.button(this,"Thử im lặng · không gửi",false,v -> new AlertDialog.Builder(this)
                .setTitle("Thử chế độ im lặng?")
                .setMessage("Điện thoại sẽ tắt âm thanh. Không gửi cảnh báo. Khi thử xong, bấm Khôi phục âm thanh trong Tiến trình cảnh báo.")
                .setNegativeButton("Để sau",null).setPositiveButton("Thử im lặng",(d,w) -> {
                    quiet.silence(); refreshStatus(); message(quiet.status()+"\nKhông có tin nhắn hoặc vị trí nào được gửi.");
                }).show()));
        addText(tools,"Không cần PC để cảnh báo. Zalo cần mạng; SMS cần SIM có sóng. Bật Vị trí trong thiết lập Android trước khi chia sẻ hành trình.",13,UiKit.MUTED);
        addText(tools,"Chế độ im lặng áp dụng cho âm lượng mà Android cho phép. Một số âm bắt buộc hoặc cuộc gọi đang diễn ra có thể vẫn phát; Alex không bảo đảm chặn mọi âm thanh.",13,UiKit.MUTED);
    }

    private int dp(int value) { return UiKit.dp(this, value); }
    private TextView addText(LinearLayout parent, String text, int size, int color) {
        TextView view = UiKit.text(this, text, size, color, false);
        parent.addView(view, UiKit.space(this, -1, -2, 8, 10));
        return view;
    }
    private void levelCard(LinearLayout parent, int level, String title, String detail, int color) {
        LinearLayout card = UiKit.card(this);
        parent.addView(card, UiKit.space(this, -1, -2, 0, 12));
        card.setPadding(dp(16),dp(16),dp(16),dp(14));
        card.setElevation(0);
        card.setBackground(UiKit.outline(level == 3 ? UiKit.BLUSH : level == 2 ? 0xfffff5e4 : UiKit.PALE, level == 3 ? 0xffedc7cd : UiKit.BORDER,24,this));
        card.addView(UiKit.text(this, "CẤP " + level + "   /   " + title, 18, color, true));
        addText(card, detail, 14, UiKit.MUTED);
        HoldButton button = new HoldButton(this, "Giữ 3 giây • Cấp " + level, color, () -> activate(level));
        card.addView(button, UiKit.space(this, -1, -2, 4, 0));
        holds.add(button);
        TextView feedback = addText(card, "", 13, color);
        feedback.setVisibility(View.GONE);
        levelStatus.add(feedback);
        button.onReleasedEarly(() -> { feedback.setVisibility(View.VISIBLE); feedback.setText("Đã hủy. Giữ đủ 3 giây để kích hoạt."); });
    }
    private boolean locationOn() { return getSystemService(LocationManager.class).isLocationEnabled(); }
    private void activate(int level) {
        activate(level, false);
    }
    private void activate(int level, boolean testOnly) {
        if (level == 3 && !testOnly) quiet.silence();
        if (testOnly) {
            if (!ZaloAlertService.available()) { message("Hỗ trợ Zalo chưa sẵn sàng. Bật lại trong Trợ năng."); return; }
            if (!ZaloAlertService.preview(this, 0, level)) message("Đang có thao tác Zalo. Dừng thao tác hiện tại trước khi thử.");
            refreshStatus(); return;
        }
        AlertPlan plan = new AlertPlan(level);
        for (int person : plan.recipients) {
            if (!store.verified(person)) { message("Hãy thử tìm đúng " + store.name(person) + " trong Thiết lập trước khi dùng thật."); return; }
        }
        if (level == 3 && (AlertPlan.phone(store.phone(0)).isEmpty() || AlertPlan.phone(store.phone(1)).isEmpty()
                || checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED
                || !AlertSms.hasSim(this, store.sim()))) {
            message("Cấp 3 cần số điện thoại của cả hai người, quyền SMS và một SIM đang hoạt động. Vào Thiết lập để hoàn tất."); return;
        }
        if (level != 3 && (!ZaloAlertService.available() || (level == 1 && !locationOn()))) {
            message("Bật quyền hỗ trợ Zalo; cấp 1 cần bật thêm Vị trí trong Thiết lập."); return;
        }
        if (level < store.level()) { message("Phiên đang ở cấp " + store.level() + ". Xem kết quả từng kênh; không chạy lại cấp thấp hơn."); return; }
        if (level == store.level()) {
            if (ZaloAlertService.busy()) { message("Đang thao tác Zalo. Xem tiến trình phía dưới; không cần nhấn lại."); return; }
            if (store.hasPendingZalo(plan)) {
                if (!ZaloAlertService.start(this, store.run(), plan)) message("Hỗ trợ Zalo chưa sẵn sàng. Bật lại trong Trợ năng rồi giữ lại nút cùng cấp.");
                refreshStatus(); return;
            }
            message("Các bước cấp này đã được yêu cầu. Alex không gửi lặp. Xem kết quả từng kênh hoặc kết thúc phiên trước khi bắt đầu cảnh báo mới."); return;
        }
        // A higher alert replaces queued lower-level Zalo steps; dispatch claims survive.
        if (ZaloAlertService.busy()) ZaloAlertService.cancel();
        String run = store.begin(level);
        if (run.isEmpty()) { message("Cấp này đã kích hoạt. Alex không tự gửi lặp; bạn có thể nâng cấp hoặc kết thúc phiên."); return; }
        if (plan.sms) for (int person : plan.recipients) AlertSms.send(this, store, run, person);
        if (!ZaloAlertService.available()) {
            for (int person : plan.recipients) store.status(run, "zalo" + person,
                    "Chưa thao tác Zalo: cần bật quyền hỗ trợ. Xem SMS riêng bên dưới.");
        } else if (!ZaloAlertService.start(this, run, plan)) {
            for (int person : plan.recipients) store.status(run, "zalo" + person, "Không khởi động được Zalo. Giữ lại nút cùng cấp để tiếp tục các bước chưa gửi.");
        }
        refreshStatus();
    }
    private void refreshStatus() {
        if (readiness == null) return;
        String ready = "Vị trí: " + (locationOn() ? "bật" : "tắt") + "   •   Hỗ trợ Zalo: "
                + (ZaloAlertService.available() ? "sẵn sàng" : "chưa bật");
        if (!ready.contentEquals(readiness.getText())) readiness.setText(ready);
        String qs = quiet.status();
        if (!qs.contentEquals(quietStatus.getText())) quietStatus.setText(qs);
        restoreAudio.setVisibility(quiet.active() ? View.VISIBLE : View.GONE);
        stopAction.setVisibility(ZaloAlertService.busy() ? View.VISIBLE : View.GONE);
        endAction.setVisibility(store.level() > 0 ? View.VISIBLE : View.GONE);
        for (int i = 0; i < levelStatus.size(); i++) {
            int level = i + 1;
            if (level <= store.level()) {
                levelStatus.get(i).setVisibility(View.VISIBLE);
                String value = level == store.level() ? "Phiên cấp " + level + ": " + store.status("zalo0")
                        : "Phiên hiện ở cấp " + store.level() + ". Cấp thấp hơn không chạy lại.";
                if (!value.contentEquals(levelStatus.get(i).getText())) levelStatus.get(i).setText(value);
            } else if (levelStatus.get(i).getText().toString().startsWith("Phiên ")) {
                levelStatus.get(i).setText(""); levelStatus.get(i).setVisibility(View.GONE);
            }
        }
        StringBuilder text = new StringBuilder();
        if (store.level() > 0) {
            text.append("Phiên đang ở cấp ").append(store.level()).append(". Không tự gửi lặp.\n");
            for (int i : new AlertPlan(store.level()).recipients) {
                text.append("\n").append(store.name(i)).append("\nZalo: ").append(store.status("zalo" + i));
                text.append("\nHành trình: ").append(store.status("location" + i));
                if (store.level() > 1) text.append("\nTin nhắn: ").append(store.status("message" + store.level() + ":" + i));
                if (store.level() == 3) text.append("\nSMS: ").append(store.status("sms" + i));
                text.append("\n");
            }
        } else text.append("Chưa có cảnh báo. Thử luồng trước khi sử dụng.");
        String previewStatus = ZaloAlertService.previewStatus();
        if (!previewStatus.isEmpty()) text.append("\nThử: ").append(previewStatus);
        if (!text.toString().contentEquals(results.getText())) results.setText(text);
    }
    private void message(String text) {
        new AlertDialog.Builder(this).setTitle("Cảnh báo Alex").setMessage(text).setPositiveButton("Đã hiểu", null).show();
    }
    private void preview() {
        new AlertDialog.Builder(this).setTitle("Chọn người để thử, không gửi")
                .setItems(new String[]{store.name(0), store.name(1)}, (d, which) -> {
                    if (!ZaloAlertService.available()) { message("Vào Thiết lập và bật Hỗ trợ Zalo trước."); return; }
                    if (!ZaloAlertService.preview(this, which, 1)) message("Đang có thao tác Zalo. Dừng lượt hiện tại rồi thử lại.");
                }).setNegativeButton("Hủy", null).show();
    }
    private void quietSettings() {
        try { startActivity(new Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS)); }
        catch (Exception ex) { message("Mở Cài đặt Android → Không làm phiền → Quyền truy cập, cho phép Alex."); }
    }
    private void testLevelTwo() {
        HoldButton button = new HoldButton(this, "Giữ 3 giây • THỬ cấp 2", 0xff956414, () -> activate(2, true));
        new AlertDialog.Builder(this).setTitle("Thử nút cấp 2 — KHÔNG GỬI")
                .setMessage("Giữ nút bên dưới. Alex kiểm tra mở đúng Zalo, ô gửi và lựa chọn hành trình. Không nhập hay gửi tin, không chia sẻ vị trí và không gọi SMS.")
                .setView(button).setNegativeButton("Đóng", null).show();
        button.onReleasedEarly(() -> button.setText("Chưa đủ 3 giây • thử giữ lại"));
    }
    private void setup() {
        if (store.level() > 0 || ZaloAlertService.busy()) {
            message("Kết thúc phiên cảnh báo / lượt thử trước khi đổi người nhận hoặc SIM."); return;
        }
        LinearLayout content = UiKit.column(this);
        content.setPadding(dp(18), dp(4), dp(18), dp(20));
        ScrollView scroll = new ScrollView(this); scroll.addView(content);
        EditText[] names = new EditText[2], phones = new EditText[2];
        addText(content, "Số điện thoại chỉ lưu mã hóa trên máy, không gửi cho Alex PC. SMS cấp 3 có thể tính phí theo SIM.", 14, UiKit.MUTED);
        for (int i = 0; i < 2; i++) {
            addText(content, "Người " + (i + 1) + " — tên đúng trong Zalo", 15, UiKit.INK);
            names[i] = new EditText(this); UiKit.field(names[i],"Tên trong Zalo"); names[i].setSingleLine(true); names[i].setText(store.name(i)); content.addView(names[i]);
            names[i].setContentDescription("Tên Zalo người " + (i + 1));
            phones[i] = new EditText(this); UiKit.field(phones[i],"Số điện thoại nhận SMS"); phones[i].setSingleLine(true); phones[i].setInputType(InputType.TYPE_CLASS_PHONE);
            phones[i].setHint("Số điện thoại nhận SMS"); phones[i].setText(store.phone(i)); content.addView(phones[i]);
            phones[i].setContentDescription("Số nhận SMS người " + (i + 1));
        }
        List<SubscriptionInfo> sims = AlertSms.sims(this);
        List<String> labels = new ArrayList<>(); labels.add("Chọn SIM để gửi SMS");
        int selection = 0;
        for (SubscriptionInfo sim : sims) {
            labels.add("SIM " + (sim.getSimSlotIndex() + 1) + " • " + sim.getCarrierName());
            if (sim.getSubscriptionId() == store.sim()) selection = labels.size() - 1;
        }
        Spinner simChoice = new Spinner(this);
        simChoice.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, labels));
        simChoice.setSelection(selection); simChoice.setMinimumHeight(dp(48)); content.addView(simChoice);
        content.addView(UiKit.button(this, "Cấp quyền SMS và xem SIM", false, v -> {
            requestPermissions(new String[]{Manifest.permission.SEND_SMS, Manifest.permission.READ_PHONE_STATE}, 70);
        }));
        addText(content, "Sau khi cấp quyền, đóng rồi mở lại Thiết lập để chọn SIM.", 13, UiKit.MUTED);
        content.addView(UiKit.button(this, "Bật / kiểm tra Vị trí", false, v -> startActivity(new Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS))), UiKit.space(this,-1,-2,8,0));
        content.addView(UiKit.button(this, "Bật hỗ trợ thao tác Zalo", false, v -> new AlertDialog.Builder(this)
                .setTitle("Quyền hỗ trợ Zalo")
                .setMessage("Alex chỉ xem và thao tác giao diện Zalo khi bạn nhấn giữ cảnh báo hoặc bấm Thử. Alex sẽ tìm tên người, chia sẻ hành trình và gửi đúng nội dung đã chọn. Không ghi lại cuộc chat. Trong màn hình tiếp theo bật ‘Alex — cảnh báo qua Zalo’.")
                .setNegativeButton("Chưa bật", null).setPositiveButton("Mở cài đặt", (a,b) -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))).show()), UiKit.space(this,-1,-2,8,0));
        if (Build.VERSION.SDK_INT >= 33) content.addView(UiKit.button(this, "Cho phép thông báo tiến trình", false,
                v -> requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 71)),UiKit.space(this,-1,-2,8,0));
        addText(content, "Cấp 2 — Zalo cho người thân 1:\n" + AlertPlan.CALL + "\n\nCấp 3 — Zalo và SMS cho cả hai:\n" + AlertPlan.SOS, 14, UiKit.INK);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("Thiết lập cảnh báo").setView(scroll)
                .setNegativeButton("Đóng", null).setPositiveButton("Lưu", null).create();
        dialog.setOnShowListener(d -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            String[] ns = {names[0].getText().toString().trim(), names[1].getText().toString().trim()};
            String[] ps = {phones[0].getText().toString(), phones[1].getText().toString()};
            if (ns[0].isEmpty() || ns[1].isEmpty() || AlertPlan.contactKey(ns[0]).equals(AlertPlan.contactKey(ns[1]))) {
                message("Hai tên Zalo phải khác nhau và không để trống."); return;
            }
            for (String p : ps) if (!p.trim().isEmpty() && AlertPlan.phone(p).isEmpty()) {
                message("Số điện thoại cần 9–15 chữ số, có thể bắt đầu bằng +."); return;
            }
            if (!ps[0].isEmpty() && AlertPlan.canonicalPhone(ps[0]).equals(AlertPlan.canonicalPhone(ps[1]))) {
                message("Hai người nhận đang trùng số điện thoại."); return;
            }
            int choice = simChoice.getSelectedItemPosition();
            try {
                store.save(ns, new String[]{AlertPlan.phone(ps[0]), AlertPlan.phone(ps[1])}, choice > 0 ? sims.get(choice-1).getSubscriptionId() : -1);
                dialog.dismiss(); refreshStatus();
            } catch (Exception ex) { message("Không lưu được số điện thoại an toàn. Hãy thử lại."); }
        }));
        dialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        dialog.show();
    }
    @Override public void onResume() {
        super.onResume(); handler.post(refresh);
        int person = ZaloAlertService.previewReadyPerson();
        if (person >= 0) {
            ZaloAlertService.clearPreviewReady();
            new AlertDialog.Builder(this).setTitle("Đúng người nhận?")
                    .setMessage("Bạn vừa kiểm tra cuộc trò chuyện của " + store.name(person)
                            + " và lựa chọn hành trình 8 giờ. Xác nhận đây đúng là người bạn muốn nhận cảnh báo? Chưa có tin hay vị trí nào được gửi.")
                    .setNegativeButton("Chưa đúng", null).setPositiveButton("Đúng người nhận", (d, w) -> store.verify(person)).show();
        }
    }
    @Override public void onPause() {
        handler.removeCallbacks(refresh);
        for (HoldButton hold : holds) hold.cancelHold();
        super.onPause();
    }
}
