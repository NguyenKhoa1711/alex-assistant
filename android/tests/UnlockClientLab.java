package vn.alex.phone;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.security.cert.Certificate;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLHandshakeException;

/** Deterministic tests of production client policy. Never opens sockets or sends keys. */
public final class UnlockClientLab {
    static int passed;
    static byte[] fixture() { return new byte[]{49,50,51,52}; }
    static void check(boolean condition) { if(!condition) throw new AssertionError(); }
    interface Case { void run() throws Exception; }
    static void test(String name, Case action) throws Exception {
        try { action.run(); passed++; System.out.println("PASS " + name); }
        catch(Throwable error) { throw new AssertionError("FAIL " + name, error); }
    }
    static boolean wiped(byte[] data) { for(byte b:data) if(b!=0) return false; return true; }
    static final String NONCE="11111111111111111111111111111111";
    static final UnlockTransport.Endpoint ENDPOINT=new UnlockTransport.Endpoint("192.168.1.10",8768,
        "1111111111111111111111111111111111111111111111111111111111111111","public-test-token");

    static final class Fake extends HttpsURLConnection implements UnlockTransport.ConnectionFactory {
        int opens, outputCalls, writes, responseCalls, inputCalls, status=200;
        boolean disconnected, closed, tlsFailure, connectFailure, writeFailure, responseFailure, readFailure, nullInput;
        AtomicBoolean cancelOnOpen, cancelOnStream, cancelAfterWrite;
        byte[] response="{\"status\":\"unlocked\"}".getBytes("UTF-8");
        Fake() throws Exception { super(new URL("https://192.168.1.10:8768")); }
        public HttpsURLConnection open(UnlockTransport.Endpoint endpoint,String path,int length) {
            check(endpoint==ENDPOINT); opens++;
            if(cancelOnOpen!=null) cancelOnOpen.set(true);
            return this;
        }
        public OutputStream getOutputStream() throws IOException {
            outputCalls++;
            if(tlsFailure) throw new SSLHandshakeException("public fixture");
            if(connectFailure) throw new IOException("public fixture");
            if(cancelOnStream!=null) cancelOnStream.set(true);
            return new ByteArrayOutputStream() {
                @Override public void write(byte[] value) throws IOException {
                    writes++;
                    if(cancelAfterWrite!=null) cancelAfterWrite.set(true);
                    if(writeFailure) throw new IOException("public fixture");
                    // Count only; do not retain even the synthetic PIN.
                }
            };
        }
        public int getResponseCode() throws IOException {
            responseCalls++; if(responseFailure) throw new SocketTimeoutException("public fixture"); return status;
        }
        public InputStream getInputStream() throws IOException {
            inputCalls++;
            if(readFailure) throw new IOException("public fixture");
            if(nullInput) return null;
            return new ByteArrayInputStream(response) { @Override public void close() { closed=true; } };
        }
        public InputStream getErrorStream() { throw new AssertionError("Must not parse error body"); }
        public void disconnect() { disconnected=true; }
        public void connect() {}
        public boolean usingProxy() { return false; }
        public String getCipherSuite() { return "TEST-ONLY"; }
        public Certificate[] getLocalCertificates() { return null; }
        public Certificate[] getServerCertificates() { return null; }
    }
    static UnlockTransport.Response send(Fake f,AtomicBoolean cancel) {
        byte[] digits=fixture();
        try { return UnlockTransport.post(ENDPOINT,"/unlock/submit",digits,NONCE,cancel,f); }
        finally { Arrays.fill(digits,(byte)0); }
    }
    static void outcome(Fake f, String expected) {
        check(expected.equals(send(f,new AtomicBoolean()).status));
        check(f.opens==1 && f.outputCalls==1 && f.disconnected);
    }
    public static void main(String[] args) throws Exception {
        test("unlock disabled until fresh locked status",()->{
            for(String status:new String[]{null,"","unlocked","offline","not_paired","service_unavailable","certificate_error","unknown_result"})
                check(!UnlockAttempt.canStart(true,status,false));
            check(UnlockAttempt.canStart(true,"locked",false));
            check(!UnlockAttempt.canStart(false,"locked",false));
            check(!UnlockAttempt.canStart(true,"locked",true));
        });
        test("confirmation transfers buffer exactly once",()->{
            byte[] b=fixture(); UnlockAttempt a=new UnlockAttempt(71,b,1000);
            check(a.confirm(true,59999)==b); check(a.confirm(true,60000)==null);
            check(a.wasClaimed()); Arrays.fill(b,(byte)0);
        });
        test("cancel wipes pending buffer",()->{
            byte[] b=fixture(); UnlockAttempt a=new UnlockAttempt(71,b,1000); a.cancel();
            check(wiped(b)); check(a.confirm(true,1001)==null);
        });
        test("rejected confirmation wipes pending buffer",()->{
            byte[] b=fixture(); UnlockAttempt a=new UnlockAttempt(71,b,1000);
            check(a.confirm(false,1001)==null && wiped(b));
        });
        test("exact deadline rejects even without timer callback",()->{
            byte[] b=fixture(); UnlockAttempt a=new UnlockAttempt(71,b,1000);
            check(a.confirm(true,61000)==null && a.isExpired() && wiped(b));
        });
        test("return after device sleep rejects expired authentication",()->{
            byte[] b=fixture(); UnlockAttempt a=new UnlockAttempt(71,b,1000);
            check(a.confirm(true,300000)==null && wiped(b));
        });
        test("clock rollback fails closed",()->{
            byte[] b=fixture(); UnlockAttempt a=new UnlockAttempt(71,b,1000);
            check(a.confirm(true,999)==null && wiped(b));
        });
        test("expiry callback is harmless after worker takes buffer",()->{
            byte[] b=fixture(); UnlockAttempt a=new UnlockAttempt(71,b,1000);
            check(a.confirm(true,2000)==b); check(!a.expire(100000)); check(!wiped(b));
            Arrays.fill(b,(byte)0);
        });
        test("new attempt does not reset old cancellation",()->{
            UnlockAttempt old=new UnlockAttempt(71,fixture(),1000); old.cancel();
            UnlockAttempt next=new UnlockAttempt(72,fixture(),2000);
            check(old.cancelled.get() && !next.cancelled.get() && old.requestCode!=next.requestCode);
            old.cancel(); check(!next.cancelled.get()); next.cancel();
        });
        test("success is submitted once and closes response",()->{
            Fake f=new Fake(); UnlockTransport.Response r=send(f,new AtomicBoolean());
            check(r.status==null && r.json.equals("{\"status\":\"unlocked\"}"));
            check(f.opens==1 && f.outputCalls==1 && f.writes==1 && f.responseCalls==1 && f.closed && f.disconnected);
            check(("Bearer "+ENDPOINT.token).equals(f.getRequestProperty("Authorization")));
            check(NONCE.equals(f.getRequestProperty("X-Alex-Unlock-Challenge")));
        });
        test("empty 401 maps to pairing error without parsing body",()->{ Fake f=new Fake(); f.status=401; outcome(f,"not_paired"); check(f.inputCalls==0); });
        test("HTML 403 maps to pairing error without parsing body",()->{ Fake f=new Fake(); f.status=403; outcome(f,"not_paired"); check(f.inputCalls==0); });
        test("302 never follows redirect",()->{ Fake f=new Fake(); f.status=302; outcome(f,"redirect_blocked"); check(f.writes==1 && f.inputCalls==0); });
        test("307 never resends credentials",()->{ Fake f=new Fake(); f.status=307; outcome(f,"redirect_blocked"); check(f.writes==1 && f.inputCalls==0); });
        test("server error does not retry",()->{ Fake f=new Fake(); f.status=503; outcome(f,"unknown_result"); check(f.writes==1); });
        test("TLS failure is distinct and sends no PIN",()->{ Fake f=new Fake(); f.tlsFailure=true; outcome(f,"certificate_error"); check(f.writes==0); });
        test("connection failure sends no PIN",()->{ Fake f=new Fake(); f.connectFailure=true; outcome(f,"offline"); check(f.writes==0); });
        test("partial write is ambiguous and never retried",()->{ Fake f=new Fake(); f.writeFailure=true; outcome(f,"unknown_result"); check(f.writes==1); });
        test("lost response is ambiguous and never retried",()->{ Fake f=new Fake(); f.responseFailure=true; outcome(f,"unknown_result"); check(f.writes==1); });
        test("read failure is ambiguous",()->{ Fake f=new Fake(); f.readFailure=true; outcome(f,"unknown_result"); });
        test("missing body is handled",()->{ Fake f=new Fake(); f.nullInput=true; outcome(f,"unknown_result"); });
        test("oversized body is bounded and closed",()->{ Fake f=new Fake(); f.response=new byte[8193]; outcome(f,"unknown_result"); check(f.closed); });
        test("cancel before request opens no connection",()->{
            Fake f=new Fake(); check("cancelled".equals(send(f,new AtomicBoolean(true)).status)); check(f.opens==0);
        });
        test("cancel after connection creation prevents stream access",()->{
            Fake f=new Fake(); AtomicBoolean c=new AtomicBoolean(); f.cancelOnOpen=c;
            check("cancelled".equals(send(f,c).status)); check(f.outputCalls==0 && f.writes==0 && f.disconnected);
        });
        test("cancel during TLS prevents PIN write",()->{
            Fake f=new Fake(); AtomicBoolean c=new AtomicBoolean(); f.cancelOnStream=c;
            check("cancelled".equals(send(f,c).status)); check(f.outputCalls==1 && f.writes==0 && f.disconnected);
        });
        test("cancel after writing cannot claim nothing sent",()->{
            Fake f=new Fake(); AtomicBoolean c=new AtomicBoolean(); f.cancelAfterWrite=c; f.responseFailure=true;
            check("unknown_result".equals(send(f,c).status)); check(f.writes==1 && f.disconnected);
        });
        test("unrecognized endpoint path rejected before connection",()->{
            Fake f=new Fake(); check("invalid_request".equals(UnlockTransport.post(ENDPOINT,"/other",fixture(),NONCE,null,f).status)); check(f.opens==0);
        });
        test("public host rejected before factory",()->{
            Fake f=new Fake(); UnlockTransport.Endpoint remote=new UnlockTransport.Endpoint("8.8.8.8",8768,ENDPOINT.fingerprint,ENDPOINT.token);
            check("invalid_endpoint".equals(UnlockTransport.post(remote,"/unlock/status",new byte[0],null,null,f).status)); check(f.opens==0);
        });
        test("bad challenge rejected before connection",()->{
            Fake f=new Fake(); check("expired_challenge".equals(UnlockTransport.post(ENDPOINT,"/unlock/submit",fixture(),"bad",null,f).status)); check(f.opens==0);
        });
        test("invalid PIN rejected before connection",()->{
            Fake f=new Fake(); check("invalid_pin".equals(UnlockTransport.post(ENDPOINT,"/unlock/submit",new byte[]{1,2,3,4},NONCE,null,f).status)); check(f.opens==0);
        });
        test("PIN cannot be attached to a status request",()->{
            Fake f=new Fake(); check("invalid_request".equals(UnlockTransport.post(ENDPOINT,"/unlock/status",fixture(),null,null,f).status)); check(f.opens==0);
        });
        test("production connection options disable redirects before connect",()->{
            HttpsURLConnection c=PinnedTls.open(ENDPOINT.host,8768,"/unlock/submit",ENDPOINT.fingerprint,5000,25000,4);
            try {
                check(!c.getInstanceFollowRedirects() && c.getDoOutput() && "POST".equals(c.getRequestMethod()));
                check(c.getConnectTimeout()==5000 && c.getReadTimeout()==25000);
                check(c.getSSLSocketFactory()!=HttpsURLConnection.getDefaultSSLSocketFactory());
            } finally { c.disconnect(); }
        });
        System.out.println("RESULT "+passed+" passed; offline client-policy tests only, no device unlock or live TLS");
    }
}
