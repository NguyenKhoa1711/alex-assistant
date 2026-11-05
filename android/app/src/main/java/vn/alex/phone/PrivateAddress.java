package vn.alex.phone;

/** Only literal LAN or Tailscale IPv4 addresses, never public hosts or DNS aliases. */
final class PrivateAddress {
    static boolean allowed(String host) {
        if (host == null || !host.matches("[0-9]{1,3}(\\.[0-9]{1,3}){3}")) return false;
        String[] parts=host.split("\\."); int[] n=new int[4];
        for(int i=0;i<4;i++) {
            if(parts[i].length()>1 && parts[i].charAt(0)=='0') return false;
            n[i]=Integer.parseInt(parts[i]); if(n[i]>255) return false;
        }
        return n[0]==10 || (n[0]==172 && n[1]>=16 && n[1]<=31)
            || (n[0]==192 && n[1]==168) || (n[0]==100 && n[1]>=64 && n[1]<=127);
    }
    static boolean remote(String host) { return allowed(host) && host.startsWith("100."); }
}
