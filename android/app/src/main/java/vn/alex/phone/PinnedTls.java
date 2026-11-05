package vn.alex.phone;

import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/** Shared by the APK and the JVM transport verification harness. */
final class PinnedTls {
    static HttpsURLConnection open(String host,int port,String path,String fingerprint,
                                   int connectTimeout,int readTimeout,int length) throws Exception {
        if(fingerprint==null || !fingerprint.matches("[0-9a-f]{64}")) throw new CertificateException("Invalid PC fingerprint");
        TrustManager[] managers={new X509TrustManager() {
            public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
            public void checkClientTrusted(X509Certificate[] chain,String type) throws CertificateException { throw new CertificateException("Client certificate not accepted"); }
            public void checkServerTrusted(X509Certificate[] chain,String type) throws CertificateException {
                checkCertificate(chain,fingerprint);
            }
        }};
        SSLContext ssl=SSLContext.getInstance("TLS"); ssl.init(null,managers,new SecureRandom());
        HttpsURLConnection connection=(HttpsURLConnection)new URL("https://"+host+":"+port+path).openConnection();
        connection.setSSLSocketFactory(ssl.getSocketFactory());
        connection.setHostnameVerifier((hostname,session)->hostname.equals(host));
        connection.setRequestMethod("POST"); connection.setInstanceFollowRedirects(false);
        connection.setConnectTimeout(connectTimeout); connection.setReadTimeout(readTimeout);
        connection.setDoOutput(true); connection.setFixedLengthStreamingMode(length);
        return connection;
    }
    static void checkCertificate(X509Certificate[] chain,String fingerprint) throws CertificateException {
        if(fingerprint==null || !fingerprint.matches("[0-9a-f]{64}")) throw new CertificateException("Invalid PC fingerprint");
        if(chain==null || chain.length==0) throw new CertificateException("Missing PC certificate");
        try {
            byte[] digest=MessageDigest.getInstance("SHA-256").digest(chain[0].getEncoded());
            StringBuilder hex=new StringBuilder();
            for(byte b:digest) hex.append(String.format("%02x",b & 0xff));
            if(!MessageDigest.isEqual(hex.toString().getBytes(StandardCharsets.US_ASCII),fingerprint.getBytes(StandardCharsets.US_ASCII)))
                throw new CertificateException("PC fingerprint does not match QR code");
        } catch(CertificateException e) { throw e; }
        catch(Exception e) { throw new CertificateException(e); }
    }
}
