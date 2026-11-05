package vn.alex.phone;
public class PrivateAddressTest {
    public static void main(String[] args) {
        for(String host:new String[]{"192.168.42.110","10.0.0.1","172.16.0.2","172.31.255.254","100.64.0.1","100.127.255.254"})
            if(!PrivateAddress.allowed(host)) throw new AssertionError("private address rejected");
        for(String host:new String[]{"127.0.0.1","8.8.8.8","100.63.0.1","100.128.0.1","172.32.0.1","192.168.999.1","192.168.01.1","localhost","user@100.64.0.1","100.64.0.1/path","::1"})
            if(PrivateAddress.allowed(host)) throw new AssertionError("unsafe address accepted");
        if(PrivateAddress.allowed(null)) throw new AssertionError("null");
        System.out.println("PASS: 18 literal LAN/Tailscale address cases.");
    }
}
