package vn.alex.phone;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.cert.CertificateException;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLException;

/** Bounded, non-retrying transport dedicated to unlock requests. No response or exception logging. */
final class UnlockTransport {
    static final class Endpoint {
        final String host, fingerprint, token;
        final int port;
        Endpoint(String host, int port, String fingerprint, String token) {
            this.host = host; this.port = port; this.fingerprint = fingerprint; this.token = token;
        }
    }
    static final class Response {
        final String status, json;
        private Response(String status, String json) { this.status = status; this.json = json; }
        static Response status(String value) { return new Response(value, null); }
        static Response json(String value) { return new Response(null, value); }
    }
    interface ConnectionFactory {
        HttpsURLConnection open(Endpoint endpoint, String path, int length) throws Exception;
    }
    private static final ConnectionFactory PINNED = (endpoint, path, length) -> PinnedTls.open(
        endpoint.host, endpoint.port, path, endpoint.fingerprint, 5000, 25000, length);

    static Response post(Endpoint endpoint, String path, byte[] body, String nonce, AtomicBoolean cancelled) {
        return post(endpoint, path, body, nonce, cancelled, PINNED);
    }

    // Factory is injectable only at this package-level test boundary; production always uses PINNED.
    static Response post(Endpoint endpoint, String path, byte[] body, String nonce,
                         AtomicBoolean cancelled, ConnectionFactory factory) {
        boolean submitting = "/unlock/submit".equals(path);
        if (!submitting && !"/unlock/status".equals(path) && !"/unlock/challenge".equals(path))
            return Response.status("invalid_request");
        if (endpoint == null || !PrivateAddress.allowed(endpoint.host) || endpoint.port < 1 || endpoint.port > 65535)
            return Response.status("invalid_endpoint");
        if (submitting && (nonce == null || !nonce.matches("[0-9a-f]{32}")))
            return Response.status("expired_challenge");
        if (body == null || (!submitting && body.length != 0)) return Response.status("invalid_request");
        if (submitting) {
            if (body.length < 4 || body.length > 20) return Response.status("invalid_pin");
            for (byte digit : body) if (digit < 48 || digit > 57) return Response.status("invalid_pin");
        }
        if (cancelled != null && cancelled.get()) return Response.status("cancelled");
        HttpsURLConnection connection = null;
        boolean bodyStarted = false;
        try {
            connection = factory.open(endpoint, path, body.length);
            connection.setRequestProperty("Content-Type", "application/octet-stream");
            connection.setRequestProperty("Authorization", "Bearer " + endpoint.token);
            if (nonce != null) connection.setRequestProperty("X-Alex-Unlock-Challenge", nonce);
            if (cancelled != null && cancelled.get()) return Response.status("cancelled");
            try (OutputStream output = connection.getOutputStream()) {
                // Opening the stream may block during TLS. Check again BEFORE writing any PIN.
                if (cancelled != null && cancelled.get()) return Response.status("cancelled");
                bodyStarted = true;
                output.write(body);
            }
            int status = connection.getResponseCode();
            // Handle errors without parsing an empty/HTML body, and never follow a redirect.
            if (status == 401 || status == 403) return Response.status("not_paired");
            if (status >= 300 && status < 400) return Response.status("redirect_blocked");
            if (status != 200) return Response.status("unknown_result");
            InputStream stream = connection.getInputStream();
            if (stream == null) return Response.status("unknown_result");
            try (InputStream input = stream; ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                byte[] chunk = new byte[1024];
                int n;
                while ((n = input.read(chunk)) != -1) {
                    if (bytes.size() + n > 8192) return Response.status("unknown_result");
                    bytes.write(chunk, 0, n);
                }
                return Response.json(new String(bytes.toByteArray(), StandardCharsets.UTF_8));
            }
        } catch (Exception error) {
            // Once a submission starts, loss of response is ambiguous: never say it was not sent.
            if (submitting && bodyStarted) return Response.status("unknown_result");
            if (error instanceof SSLException || error instanceof CertificateException)
                return Response.status("certificate_error");
            return Response.status("offline");
        } finally {
            if (connection != null) connection.disconnect();
        }
    }
}
