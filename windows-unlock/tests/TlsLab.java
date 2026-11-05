package vn.alex.phone;
import java.io.OutputStream;
import java.io.InputStream;
import java.io.IOException;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLHandshakeException;

public final class TlsLab {
    public static void main(String[] args) throws Exception {
        int port=Integer.parseInt(args[0]); String fp=args[1], mode=args[2];
        String path="/"+mode;
        if(mode.equals("wrong_certificate")) fp=new String(new char[64]).replace('\0','0');
        byte[] synthetic={49,50,51,52}; // Public fixture, not a Windows credential.
        HttpsURLConnection c=PinnedTls.open("127.0.0.1",port,path,fp,2000,2000,synthetic.length);
        c.setRequestProperty("Content-Type","application/octet-stream");
        c.setRequestProperty("Authorization","Bearer public-test-fixture");
        boolean okay=false;
        try {
            try(OutputStream stream=c.getOutputStream()) { stream.write(synthetic); }
            int status=c.getResponseCode();
            if(mode.equals("good")) okay=status==200;
            if(mode.equals("redirect")) okay=status==302 && !c.getInstanceFollowRedirects();
            if(mode.equals("unauthorized")) okay=status==401;
            if(mode.equals("no_reply")) {
                try(InputStream in=c.getInputStream()) { while(in.read()!=-1) {} }
            }
        } catch(SSLHandshakeException expected) { okay=mode.equals("wrong_certificate"); if(!okay) { System.err.println("Handshake failed: "+expected.getMessage()); if(mode.equals("good")) inspectCertificate(port,fp); } }
        catch(IOException expected) { okay=mode.equals("cut") || mode.equals("no_reply"); if(!okay) expected.printStackTrace(); }
        finally { java.util.Arrays.fill(synthetic,(byte)0); c.disconnect(); }
        if(!okay) throw new AssertionError("Transport expectation failed: "+mode);
        System.out.println("PASS "+mode);
    }
    // Read certificate metadata only, on the synthetic loopback test server; sends no HTTP/PIN.
    private static void inspectCertificate(int port,String expected) throws Exception {
        javax.net.ssl.TrustManager[] trust={new javax.net.ssl.X509TrustManager() {
            public java.security.cert.X509Certificate[] getAcceptedIssuers(){return new java.security.cert.X509Certificate[0];}
            public void checkClientTrusted(java.security.cert.X509Certificate[] c,String t){}
            public void checkServerTrusted(java.security.cert.X509Certificate[] c,String t){}
        }};
        javax.net.ssl.SSLContext ctx=javax.net.ssl.SSLContext.getInstance("TLS");ctx.init(null,trust,null);
        try(javax.net.ssl.SSLSocket sock=(javax.net.ssl.SSLSocket)ctx.getSocketFactory().createSocket("127.0.0.1",port)) {
            sock.setSoTimeout(2000);sock.startHandshake();
            java.security.cert.X509Certificate cert=(java.security.cert.X509Certificate)sock.getSession().getPeerCertificates()[0];
            StringBuilder hex=new StringBuilder();for(byte b:java.security.MessageDigest.getInstance("SHA-256").digest(cert.getEncoded())) hex.append(String.format("%02x",b & 255));
            System.err.println("DIAGNOSTIC peer_matches_fixture="+hex.toString().equals(expected)+" issuer="+cert.getIssuerX500Principal());
        }
    }
}
