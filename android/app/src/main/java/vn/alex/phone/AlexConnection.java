package vn.alex.phone;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ConnectException;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import java.util.Enumeration;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.concurrent.CompletionService;
import java.util.concurrent.ExecutorCompletionService;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLHandshakeException;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

final class AlexConnection {
    private static final String KEY_ALIAS = "alex-phone-token";
    private final SharedPreferences prefs;

    AlexConnection(Context context) {
        prefs = context.getSharedPreferences("pairing", Context.MODE_PRIVATE);
    }

    boolean isPaired() {
        return prefs.contains("token") && prefs.contains("fingerprint");
    }

    String host() { return prefs.getString("host", ""); }

    void forget() { prefs.edit().clear().commit(); }

    static final class Turn {
        final String transcript;
        final String reply;
        final int sampleRate;
        final byte[] audio;

        Turn(JSONObject data) throws Exception {
            transcript = data.getString("transcript");
            reply = data.getString("reply");
            sampleRate = data.getInt("sample_rate");
            audio = Base64.decode(data.getString("audio"), Base64.DEFAULT);
        }
    }

    void pair(Uri link) throws Exception {
        if (!"alexphone".equals(link.getScheme()) || !"pair".equals(link.getHost()))
            throw new IllegalArgumentException("Liên kết ghép nối không đúng.");
        String host = link.getQueryParameter("host");
        String fingerprint = link.getQueryParameter("fp");
        String code = link.getQueryParameter("code");
        int port = Integer.parseInt(link.getQueryParameter("port"));
        if (!PrivateAddress.allowed(host)
                || fingerprint == null || !fingerprint.matches("[0-9a-fA-F]{64}")
                || code == null || !code.matches("[0-9a-fA-F]{32}")
                || port < 1024 || port > 65535)
            throw new IllegalArgumentException("Mã ghép nối không hợp lệ hoặc không thuộc mạng nội bộ.");
        JSONObject request = new JSONObject().put("code", code);
        JSONObject response = post(host, port, fingerprint.toLowerCase(), "/pair",
                "application/json", request.toString().getBytes(StandardCharsets.UTF_8), null);
        String token = response.getString("token");
        // Persist before reporting success, even if Android closes the app immediately.
        if (!prefs.edit().putString("host", host).putInt("port", port)
                .putString("fingerprint", fingerprint.toLowerCase())
                .putString("token", encrypt(token)).commit())
            throw new IOException("Không lưu được kết nối. Kiểm tra bộ nhớ điện thoại.");
    }

    Turn sendVoice(byte[] pcm16) throws Exception {
        if (!isPaired()) throw new IllegalStateException("Hãy ghép nối điện thoại với Alex trên PC.");
        String token = decrypt(prefs.getString("token", ""));
        int port = prefs.getInt("port", 8768);
        String fingerprint = prefs.getString("fingerprint", "");
        JSONObject response;
        try {
            response = post(host(), port, fingerprint, "/turn",
                    "application/octet-stream", pcm16, token);
        } catch (HostUnavailableException unavailable) {
            if (PrivateAddress.remote(host()))
                throw new IOException("Không tới được laptop. Kiểm tra mạng riêng Tailscale trên hai máy, laptop phải đang thức và Alex đang chạy.");
            String currentHost = discoverHost(port, fingerprint, token);
            if (currentHost == null)
                throw new IOException("Đã lưu ghép nối, nhưng không tìm thấy Alex trên cùng Wi-Fi. Kiểm tra Alex trên PC và quy tắc Avast cho cổng 8768.", unavailable);
            if (!prefs.edit().putString("host", currentHost).commit())
                throw new IOException("Không lưu được địa chỉ PC mới.");
            response = post(currentHost, port, fingerprint, "/turn",
                    "application/octet-stream", pcm16, token);
        }
        return new Turn(response);
    }

    private static final class HostUnavailableException extends IOException {
        HostUnavailableException(IOException cause) { super(cause); }
    }

    JSONObject unlockStatus() throws Exception {
        return unlockPost(unlockEndpoint(), "/unlock/status", new byte[0], null, null);
    }

    JSONObject unlockWithPin(byte[] pin, java.util.concurrent.atomic.AtomicBoolean cancelled) throws Exception {
        try {
            if(cancelled.get()) return new JSONObject().put("status","cancelled");
            // Keep pairing identity and destination fixed for this entire attempt.
            UnlockTransport.Endpoint endpoint=unlockEndpoint();
            JSONObject challenge=unlockPost(endpoint,"/unlock/challenge",new byte[0],null,cancelled);
            if(!"ready".equals(challenge.optString("status"))) return challenge;
            String nonce=challenge.optString("challenge");
            if(!nonce.matches("[0-9a-f]{32}")) throw new IOException("Invalid challenge");
            if(cancelled.get()) return new JSONObject().put("status","cancelled");
            // Exactly one POST. Never rediscover a host or retry credential submission.
            return unlockPost(endpoint,"/unlock/submit",pin,nonce,cancelled);
        } finally { java.util.Arrays.fill(pin,(byte)0); }
    }

    private UnlockTransport.Endpoint unlockEndpoint() throws Exception {
        if(!isPaired()) return null;
        return new UnlockTransport.Endpoint(host(),prefs.getInt("port",8768),
            prefs.getString("fingerprint",""),decrypt(prefs.getString("token","")));
    }

    private static JSONObject unlockPost(UnlockTransport.Endpoint endpoint,String path,byte[] body,
                                         String nonce,java.util.concurrent.atomic.AtomicBoolean cancelled) throws Exception {
        if(endpoint==null) return new JSONObject().put("status","not_paired");
        UnlockTransport.Response response=UnlockTransport.post(endpoint,path,body,nonce,cancelled);
        return response.status!=null ? new JSONObject().put("status",response.status) : new JSONObject(response.json);
    }

    private static String discoverHost(int port, String fingerprint, String token) throws Exception {
        Set<String> candidates = new LinkedHashSet<>();
        Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
        while (interfaces != null && interfaces.hasMoreElements()) {
            NetworkInterface network = interfaces.nextElement();
            if (!network.isUp() || !network.getName().startsWith("wlan")) continue;
            Enumeration<InetAddress> addresses = network.getInetAddresses();
            while (addresses.hasMoreElements()) {
                InetAddress address = addresses.nextElement();
                if (!(address instanceof Inet4Address) || !address.isSiteLocalAddress()) continue;
                byte[] parts = address.getAddress();
                for (int last = 1; last < 255; last++) {
                    if (last == (parts[3] & 0xff)) continue;
                    candidates.add((parts[0] & 0xff) + "." + (parts[1] & 0xff) + "."
                            + (parts[2] & 0xff) + "." + last);
                }
            }
        }
        if (candidates.isEmpty()) return null;
        ExecutorService pool = Executors.newFixedThreadPool(32);
        CompletionService<String> found = new ExecutorCompletionService<>(pool);
        try {
            for (String candidate : candidates) found.submit(() -> {
                try (Socket probe = new Socket()) {
                    probe.connect(new InetSocketAddress(candidate, port), 400);
                    JSONObject status = post(candidate, port, fingerprint, "/status",
                            "application/json", new byte[0], token, 1500);
                    return "ready".equals(status.optString("status")) ? candidate : null;
                } catch (Exception ignored) { return null; }
            });
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(9);
            for (int remaining = candidates.size(); remaining > 0; remaining--) {
                long wait = deadline - System.nanoTime();
                if (wait <= 0) break;
                Future<String> result = found.poll(wait, TimeUnit.NANOSECONDS);
                if (result == null) break;
                String candidate = result.get();
                if (candidate != null) return candidate;
            }
            return null;
        } finally { pool.shutdownNow(); }
    }

    private static JSONObject post(String host, int port, String fingerprint, String path,
                                   String contentType, byte[] body, String token) throws Exception {
        return post(host, port, fingerprint, path, contentType, body, token, 8000);
    }

    private static JSONObject post(String host, int port, String fingerprint, String path,
                                   String contentType, byte[] body, String token,
                                   int connectTimeout) throws Exception {
        return post(host,port,fingerprint,path,contentType,body,token,connectTimeout,null);
    }

    private static JSONObject post(String host, int port, String fingerprint, String path,
                                   String contentType, byte[] body, String token,
                                   int connectTimeout, String nonce) throws Exception {
        HttpsURLConnection connection = PinnedTls.open(host, port, path, fingerprint,
                connectTimeout, path.startsWith("/unlock/") ? 25000 : "/status".equals(path) ? connectTimeout : 245000,
                body.length);
        connection.setRequestProperty("Content-Type", contentType);
        if (token != null) connection.setRequestProperty("Authorization", "Bearer " + token);
        if (nonce != null) connection.setRequestProperty("X-Alex-Unlock-Challenge",nonce);
        try {
            OutputStream output;
            try { output = connection.getOutputStream(); }
            catch (ConnectException | SocketTimeoutException | SSLHandshakeException error) {
                throw new HostUnavailableException(error);
            }
            try (OutputStream stream = output) { stream.write(body); }
            InputStream input = connection.getResponseCode() < 400 ? connection.getInputStream() : connection.getErrorStream();
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] chunk = new byte[8192];
            int n;
            while ((n = input.read(chunk)) != -1) {
                if (bytes.size() + n > (path.startsWith("/unlock/") ? 8192 : 18_000_000)) throw new IllegalStateException("Câu trả lời quá dài.");
                bytes.write(chunk, 0, n);
            }
            JSONObject data = new JSONObject(bytes.toString("UTF-8"));
            if(path.startsWith("/unlock/") && connection.getResponseCode()>=400)
                return new JSONObject().put("status", connection.getResponseCode()==401 ? "not_paired" : "unknown_result");
            if (connection.getResponseCode() >= 400) throw new IllegalStateException(data.optString("error", "Alex không trả lời."));
            return data;
        } finally { connection.disconnect(); }
    }

    private static SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(KEY_ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256).build());
            generator.generateKey();
        }
        return ((KeyStore.SecretKeyEntry) store.getEntry(KEY_ALIAS, null)).getSecretKey();
    }

    private static String encrypt(String value) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        byte[] iv = cipher.getIV();
        byte[] ciphertext = cipher.doFinal(value.getBytes(StandardCharsets.UTF_8));
        byte[] combined = new byte[iv.length + ciphertext.length];
        System.arraycopy(iv, 0, combined, 0, iv.length);
        System.arraycopy(ciphertext, 0, combined, iv.length, ciphertext.length);
        return Base64.encodeToString(combined, Base64.NO_WRAP);
    }

    private static String decrypt(String encoded) throws Exception {
        byte[] combined = Base64.decode(encoded, Base64.DEFAULT);
        byte[] iv = new byte[12];
        System.arraycopy(combined, 0, iv, 0, iv.length);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, iv));
        return new String(cipher.doFinal(combined, iv.length, combined.length - iv.length), StandardCharsets.UTF_8);
    }
}
