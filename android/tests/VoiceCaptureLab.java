package vn.alex.phone;
import android.media.AudioRecord;
import java.io.IOException;
import java.util.concurrent.*;

public class VoiceCaptureLab {
    static int checks;
    static void check(boolean value,String label) {
        if(!value) throw new AssertionError(label);
        checks++; System.out.println("PASS "+label);
    }
    public static void main(String[] args) throws Exception {
        ExecutorService worker=Executors.newSingleThreadExecutor();
        try {
            VoiceCapture capture=new VoiceCapture(); capture.start();
            AudioRecord mic=AudioRecord.latest;
            check(mic.started,"mic starts before ready is reported");
            Future<byte[]> result=worker.submit(capture::read);
            check(mic.waiting.await(2,TimeUnit.SECONDS),"legacy blocking read is in progress");
            capture.release();
            byte[] audio=result.get(2,TimeUnit.SECONDS);
            check(audio.length==3200 && audio[0]==17,"release retains recorded PCM and unblocks read");
            check(mic.freed && mic.releases==1,"mic released once after reader exits");
            capture.release(); capture.cancel();
            check(mic.releases==1,"repeated release/cancel does not close the mic again");

            VoiceCapture cancel=new VoiceCapture(); cancel.start(); mic=AudioRecord.latest;
            result=worker.submit(cancel::read);
            check(mic.waiting.await(2,TimeUnit.SECONDS),"cancel test reached blocking read");
            cancel.cancel();
            check(result.get(2,TimeUnit.SECONDS).length==0 && cancel.cancelled(),"leaving app discards captured bytes");
            check(mic.freed,"cancel frees the mic");

            VoiceCapture quick=new VoiceCapture(); quick.start(); mic=AudioRecord.latest;
            quick.release();
            check(quick.read().length==0 && mic.reads==0 && mic.freed,"quick tap never reads from a stopped mic");

            AudioRecord.failStart=true;
            try { new VoiceCapture().start(); throw new AssertionError("unstarted mic accepted"); }
            catch(IOException expected) { check(AudioRecord.latest.freed,"start failure is reported and releases mic"); }
            AudioRecord.failStart=false; AudioRecord.errorRead=true;
            VoiceCapture bad=new VoiceCapture(); bad.start();
            try { bad.read(); throw new AssertionError("read error ignored"); }
            catch(IOException expected) { check(AudioRecord.latest.freed,"read failure is not mistaken for normal release"); }
        } finally { worker.shutdownNow(); }
        System.out.println("RESULT "+checks+" capture API tests passed (no physical microphone)");
    }
}
