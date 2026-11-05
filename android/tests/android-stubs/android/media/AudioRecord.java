package android.media;
import java.util.concurrent.*;
/** Test double for API lifecycle/concurrency; not a hardware/microphone simulation. */
public class AudioRecord {
    public static final int STATE_INITIALIZED=1, RECORDSTATE_RECORDING=3;
    public static volatile AudioRecord latest;
    public static boolean failStart, errorRead;
    public boolean started, stopped, freed;
    public int reads, releases;
    public final CountDownLatch firstRead=new CountDownLatch(1), waiting=new CountDownLatch(1);
    public AudioRecord(int source,int rate,int channels,int format,int size) {
        if(source!=6 || rate!=16000 || channels!=16 || format!=2) throw new AssertionError("legacy audio format changed");
        latest=this;
    }
    public static int getMinBufferSize(int r,int c,int f) { return 4096; }
    public int getState() { return STATE_INITIALIZED; }
    public int getRecordingState() { return started ? RECORDSTATE_RECORDING : 1; }
    public void startRecording() { started=!failStart; }
    public synchronized void stop() { stopped=true; notifyAll(); }
    public synchronized void release() { freed=true; releases++; }
    public synchronized int read(byte[] b,int offset,int count) {
        if(freed) throw new AssertionError("read after release");
        if(!started) throw new AssertionError("read before start");
        reads++;
        if(errorRead) return -3;
        if(reads==1) { java.util.Arrays.fill(b,(byte)17); firstRead.countDown(); return count; }
        waiting.countDown();
        while(!stopped) try { wait(); } catch(InterruptedException e) { throw new RuntimeException(e); }
        return -3; // Android can return an error after intentional stop.
    }
}
