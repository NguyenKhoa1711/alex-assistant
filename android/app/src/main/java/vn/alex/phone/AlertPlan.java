package vn.alex.phone;

/** Fixed user-authored actions; no language model participates in dispatch. */
final class AlertPlan {
    static final long HOLD_MS = 3000;
    static final String SOS = "con đang gặp nguy hiểm, xem vị trí con gửi r tới giúp con nha, con ko gọi hay nghe máy được nên đừng gọi.";
    static final String CALL = "Mình đang cảm thấy không an toàn, hãy gọi cho mình.";
    final int level;
    final int[] recipients;
    final String message;
    final boolean sms;

    AlertPlan(int level) {
        if (level < 1 || level > 3) throw new IllegalArgumentException("Cấp không hợp lệ");
        this.level = level;
        recipients = level == 3 ? new int[]{0, 1} : new int[]{0};
        message = level == 3 ? SOS : level == 2 ? CALL : "";
        sms = level == 3;
    }

    static String phone(String value) {
        String result = value.replaceAll("[\\s().-]", "");
        if (!result.matches("\\+?[0-9]{9,15}")) return "";
        return result;
    }

    static String canonicalPhone(String value) {
        String result = phone(value);
        return result.startsWith("0") ? "+84" + result.substring(1) : result;
    }

    static String contactKey(String value) {
        return value.trim().replaceAll("\\s+", " ").toLowerCase(java.util.Locale.ROOT);
    }
}
