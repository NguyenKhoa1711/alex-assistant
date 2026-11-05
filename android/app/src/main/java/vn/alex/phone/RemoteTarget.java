package vn.alex.phone;

/** Only a numeric PC ID can enter the external link. No credentials. */
final class RemoteTarget {
    static final String PACKAGE = "com.carriez.flutter_hbb";
    static final String DOWNLOAD = "https://github.com/rustdesk/rustdesk/releases/latest";
    static String normalize(String text) {
        if (text == null || text.length() > 64) throw new IllegalArgumentException("Nhập ID RustDesk của laptop.");
        String id = text.replaceAll("[\\s\\u00a0-]", "");
        if (!id.matches("[0-9]{6,16}"))
            throw new IllegalArgumentException("ID chỉ gồm 6–16 chữ số. Không nhập PIN, mật khẩu hoặc đường link.");
        return id;
    }
    static String uri(String text) { return "rustdesk://connection/new/" + normalize(text); }
}
