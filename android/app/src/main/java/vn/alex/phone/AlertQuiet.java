package vn.alex.phone;

import android.app.NotificationManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.media.AudioManager;
import android.os.Build;

/** Saves audio settings only; does not persist PINs, locations, or conversations. */
final class AlertQuiet {
    private final QuietPolicy policy;
    private final NotificationManager notifications;
    AlertQuiet(Context context) {
        AudioManager audio = context.getSystemService(AudioManager.class);
        notifications = context.getSystemService(NotificationManager.class);
        SharedPreferences prefs = context.getSharedPreferences("alex_quiet", Context.MODE_PRIVATE);
        policy = new QuietPolicy(new QuietPolicy.Audio() {
            public int volume(int stream) { return audio.getStreamVolume(stream); }
            public void volume(int stream, int value) { audio.setStreamVolume(stream, value, 0); }
            public int ringer() { return audio.getRingerMode(); }
            public void ringer(int value) { audio.setRingerMode(value); }
            public int filter() { return notifications.getCurrentInterruptionFilter(); }
            public void filter(int value) { notifications.setInterruptionFilter(value); }
            public boolean permission() { return notifications.isNotificationPolicyAccessGranted(); }
            public boolean ownRule() { return Build.VERSION.SDK_INT >= 35; }
        }, new QuietPolicy.Journal() {
            public QuietPolicy.Snapshot load() {
                if (!prefs.getBoolean("active", false)) return null;
                int[] values = new int[QuietPolicy.STREAMS.length];
                for (int i = 0; i < values.length; i++) values[i] = prefs.getInt("volume" + i, 0);
                return new QuietPolicy.Snapshot(values, prefs.getInt("ringer", 0), prefs.getInt("filter", 1));
            }
            public boolean save(QuietPolicy.Snapshot saved) {
                SharedPreferences.Editor edit = prefs.edit().putBoolean("active", true)
                        .putInt("ringer", saved.ringer).putInt("filter", saved.filter);
                for (int i = 0; i < saved.volumes.length; i++) edit.putInt("volume" + i, saved.volumes[i]);
                return edit.commit();
            }
            public boolean clear() { return prefs.edit().clear().commit(); }
        });
    }
    boolean permitted() { return notifications.isNotificationPolicyAccessGranted(); }
    boolean active() { return policy.active(); }
    boolean silence() { return policy.silence(); }
    boolean restore() { return policy.restore(); }
    String status() {
        if (!active()) return "Cấp 3 sẽ giảm âm lượng và bật Không làm phiền."
                + (permitted() ? " Quyền đã sẵn sàng." : " Cần cấp quyền Không làm phiền trước.");
        return policy.quiet() ? "Đã kiểm tra: âm lượng bằng 0, chuông im lặng, Không làm phiền bật. Giữ đến khi bạn khôi phục."
                : "Đã yêu cầu im lặng nhưng chưa tắt được đầy đủ âm thanh. Kiểm tra quyền Không làm phiền và âm lượng máy.";
    }
}
