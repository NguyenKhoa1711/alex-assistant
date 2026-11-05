package android.os;
public class SystemClock {
    public static long elapsedRealtime() { return System.nanoTime()/1000000; }
    public static void sleep(long millis) { try { Thread.sleep(millis); } catch(InterruptedException e) { Thread.currentThread().interrupt(); } }
}
