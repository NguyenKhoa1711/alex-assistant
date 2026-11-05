package vn.alex.phone;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.UUID;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Local settings and a synchronous, at-most-once dispatch journal. No PIN or location history. */
final class AlertStore {
    private final SharedPreferences prefs;
    static final String[] NAMES = {"Đại ca", "Chanhthuanhk"};
    AlertStore(Context context) { this(context, "alex_alerts"); }
    AlertStore(Context context, String namespace) { prefs = context.getSharedPreferences(namespace, Context.MODE_PRIVATE); }
    String name(int person) { return prefs.getString("name" + person, NAMES[person]); }
    int sim() { return prefs.getInt("sim", -1); }
    String phone(int person) {
        String encoded = prefs.getString("phone" + person, "");
        if (encoded.isEmpty()) return "";
        try {
            byte[] data = Base64.decode(encoded, Base64.NO_WRAP);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, data, 0, 12));
            return new String(cipher.doFinal(data, 12, data.length - 12), StandardCharsets.UTF_8);
        } catch (Exception ex) { return ""; }
    }
    private SecretKey key() throws Exception {
        KeyStore keys = KeyStore.getInstance("AndroidKeyStore");
        keys.load(null);
        String alias = "alex-alert-contacts-v1";
        if (!keys.containsAlias(alias)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(alias,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            generator.generateKey();
        }
        return (SecretKey) keys.getKey(alias, null);
    }
    void save(String[] names, String[] phones, int sim) throws Exception {
        if (level() > 0) throw new IllegalStateException("Kết thúc phiên trước khi đổi người nhận");
        SharedPreferences.Editor editor = prefs.edit();
        for (int i = 0; i < 2; i++) {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key());
            byte[] encrypted = cipher.doFinal(phones[i].getBytes(StandardCharsets.UTF_8));
            byte[] data = new byte[12 + encrypted.length];
            System.arraycopy(cipher.getIV(), 0, data, 0, 12);
            System.arraycopy(encrypted, 0, data, 12, encrypted.length);
            editor.putString("phone" + i, Base64.encodeToString(data, Base64.NO_WRAP));
            if (!name(i).equals(names[i])) editor.remove("verified" + i);
            editor.putString("name" + i, names[i]);
        }
        if (!editor.putInt("sim", sim).commit()) throw new IllegalStateException("Không lưu được thiết lập");
    }
    boolean verified(int person) { return prefs.getBoolean("verified" + person, false); }
    void verify(int person) { prefs.edit().putBoolean("verified" + person, true).commit(); }
    int level() { return prefs.getInt("level", 0); }
    String run() { return prefs.getString("run", ""); }
    boolean isRun(String id) { return !id.isEmpty() && run().equals(id); }
    String begin(int level) {
        if (level <= level()) return "";
        String id = run();
        if (id.isEmpty()) id = UUID.randomUUID().toString();
        if (!prefs.edit().putString("run", id).putInt("level", level).commit()) return "";
        return id;
    }
    void end() {
        SharedPreferences.Editor e = prefs.edit();
        for (String key : prefs.getAll().keySet()) if (key.startsWith("job:")) e.remove(key);
        e.remove("run").remove("level").commit();
    }
    boolean claim(String id, String op) {
        synchronized (AlertStore.class) {
            if (!isRun(id) || prefs.contains("job:" + op)) return false;
            return prefs.edit().putString("job:" + op, "Đã bắt đầu; chưa có kết quả")
                    .putLong("job:" + op + ":at", System.currentTimeMillis()).commit();
        }
    }
    boolean claimed(String id, String op) { return isRun(id) && prefs.contains("job:" + op); }
    boolean hasPendingZalo(AlertPlan plan) {
        for (int person : plan.recipients) {
            if (!claimed(run(), "location" + person)) return true;
            if (!plan.message.isEmpty() && !claimed(run(), "message" + plan.level + ":" + person)) return true;
        }
        return false;
    }
    void status(String id, String op, String value) {
        synchronized (AlertStore.class) {
            if (isRun(id)) prefs.edit().putString("job:" + op, value).commit();
        }
    }
    String status(String op) {
        String value = prefs.getString("job:" + op, "Chưa thực hiện");
        if (op.matches("sms[01]") && (value.startsWith("Đang chờ") || value.contains("đang chờ nhà mạng"))
                && System.currentTimeMillis() - prefs.getLong("job:" + op + ":at", 0) > 90000)
            return "Chưa nhận đủ kết quả SMS; không tự gửi lại";
        return value;
    }
    long sharedUntil(int person) { return prefs.getLong("sharedUntil" + person, 0); }
    void shared(int person) { prefs.edit().putLong("sharedUntil" + person, System.currentTimeMillis() + 8 * 3600000L).commit(); }
    void smsPart(String id, String op, int part, int total, boolean ok) {
        synchronized (AlertStore.class) {
            if (!isRun(id)) return;
            prefs.edit().putInt("job:" + op + ":part" + part, ok ? 1 : -1).commit();
            int success = 0, failed = 0;
            for (int i = 0; i < total; i++) {
                int code = prefs.getInt("job:" + op + ":part" + i, 0);
                if (code == 1) success++;
                if (code == -1) failed++;
            }
            String value = failed > 0 ? "SMS lỗi (" + failed + "/" + total + " phần). Không tự gửi lại."
                    : success == total ? "Đã gửi qua SIM; chưa xác nhận người nhận đã đọc"
                    : "Đã gửi " + success + "/" + total + " phần; đang chờ nhà mạng";
            status(id, op, value);
        }
    }
}
