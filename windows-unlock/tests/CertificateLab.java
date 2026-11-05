package vn.alex.phone;
import java.io.FileInputStream;
import java.security.cert.CertificateFactory;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
public final class CertificateLab {
    private static int cases;
    private static void rejected(X509Certificate[] chain,String fp) throws Exception {
        try { PinnedTls.checkCertificate(chain,fp); }
        catch(CertificateException expected) { cases++; return; }
        throw new AssertionError("Unexpected certificate accepted");
    }
    public static void main(String[] args) throws Exception {
        X509Certificate cert,other;
        try(FileInputStream in=new FileInputStream(args[0])) { cert=(X509Certificate)CertificateFactory.getInstance("X.509").generateCertificate(in); }
        try(FileInputStream in=new FileInputStream(args[1])) { other=(X509Certificate)CertificateFactory.getInstance("X.509").generateCertificate(in); }
        String fp=args[2];
        PinnedTls.checkCertificate(new X509Certificate[]{cert},fp);cases++;
        rejected(null,fp);rejected(new X509Certificate[0],fp);
        rejected(new X509Certificate[]{cert},"invalid");
        rejected(new X509Certificate[]{cert},new String(new char[64]).replace('\0','0'));
        rejected(new X509Certificate[]{other,cert},fp);
        System.out.println("PASS certificate policy: "+cases+" cases; no network");
    }
}
