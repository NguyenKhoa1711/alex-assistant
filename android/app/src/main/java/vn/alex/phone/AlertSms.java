package vn.alex.phone;

import android.Manifest;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.telephony.SmsManager;
import android.telephony.SubscriptionInfo;
import android.telephony.SubscriptionManager;
import java.util.ArrayList;
import java.util.List;

final class AlertSms {
    private AlertSms() { }
    static List<SubscriptionInfo> sims(Context c) {
        if (c.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED)
            return java.util.Collections.emptyList();
        List<SubscriptionInfo> items = c.getSystemService(SubscriptionManager.class).getActiveSubscriptionInfoList();
        return items == null ? java.util.Collections.emptyList() : items;
    }
    static boolean hasSim(Context c, int id) {
        for (SubscriptionInfo sim : sims(c)) if (sim.getSubscriptionId() == id) return true;
        return false;
    }
    static void send(Context c, AlertStore store, String run, int person) {
        String op = "sms" + person;
        if (!store.claim(run, op)) return;
        try {
            if (!hasSim(c, store.sim())) throw new IllegalStateException("Chưa chọn SIM đang hoạt động");
            if (c.checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED)
                throw new IllegalStateException("Chưa cấp quyền SMS");
            String phone = AlertPlan.phone(store.phone(person));
            if (phone.isEmpty()) throw new IllegalStateException("Chưa có số điện thoại hợp lệ");
            SmsManager manager = SmsManager.getSmsManagerForSubscriptionId(store.sim());
            ArrayList<String> parts = manager.divideMessage(AlertPlan.SOS);
            ArrayList<PendingIntent> sent = new ArrayList<>();
            for (int i = 0; i < parts.size(); i++) {
                Intent result = new Intent(c, AlertSmsReceiver.class)
                        .setData(Uri.parse("alex-sms://" + run + "/" + person + "/" + i))
                        .putExtra("run", run).putExtra("op", op).putExtra("part", i).putExtra("total", parts.size());
                sent.add(PendingIntent.getBroadcast(c, i, result, PendingIntent.FLAG_IMMUTABLE));
            }
            store.status(run, op, "Đang chờ kết quả gửi từ nhà mạng");
            manager.sendMultipartTextMessage(phone, null, parts, sent, null);
            new Handler(Looper.getMainLooper()).postDelayed(() -> {
                String status = store.status(op);
                if (status.startsWith("Đang chờ") || status.contains("đang chờ nhà mạng"))
                    store.status(run, op, "Chưa nhận đủ kết quả SMS; không tự gửi lại");
            }, 90000);
        } catch (Exception e) {
            store.status(run, op, "Chưa gửi được SMS. Kiểm tra quyền, SIM và sóng di động.");
        }
    }
}
