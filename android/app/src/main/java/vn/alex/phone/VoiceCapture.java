package vn.alex.phone;

import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.SystemClock;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;

/** Original blocking capture: start before announcing readiness, stop on release. */
final class VoiceCapture {
    private final AtomicBoolean ended = new AtomicBoolean();
    private final AtomicBoolean cancelled = new AtomicBoolean();
    private AudioRecord recorder;
    synchronized void release() {
        ended.set(true);
        if (recorder != null) try { recorder.stop(); } catch (IllegalStateException ignored) { }
    }
    void cancel() { cancelled.set(true); release(); }
    boolean cancelled() { return cancelled.get(); }
    synchronized void start() throws IOException {
        if (recorder != null || ended.get()) throw new IOException("Lượt thu đã kết thúc.");
        int minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        if (minimum <= 0) throw new IOException("Không mở được mic điện thoại.");
        AudioRecord input = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION,16000,
            AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,Math.max(minimum,4096));
        try {
            if (input.getState()!=AudioRecord.STATE_INITIALIZED) throw new IOException("Mic chưa sẵn sàng.");
            input.startRecording();
            if(input.getRecordingState()!=AudioRecord.RECORDSTATE_RECORDING)
                throw new IOException("Điện thoại chưa cho Alex thu âm. Kiểm tra quyền mic.");
            recorder=input;
        } catch(Exception error) {
            input.release();
            if(error instanceof IOException) throw (IOException)error;
            throw new IOException("Không khởi động được mic. Kiểm tra quyền mic của Alex mới.",error);
        }
    }
    byte[] read() throws IOException {
        final AudioRecord input;
        synchronized(this) { input=recorder; }
        if(input==null) throw new IOException("Mic chưa được khởi động.");
        try {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream(32000);
            byte[] block = new byte[3200]; // Same blocking read as the working 1.8.1.
            long deadline=SystemClock.elapsedRealtime()+20000;
            while(!ended.get() && SystemClock.elapsedRealtime()<deadline && bytes.size()<640000) {
                int n=input.read(block,0,block.length);
                if(n<0 && !ended.get()) throw new IOException("Mic bị gián đoạn. Bạn thử giữ để nói lại nhé.");
                if(n>0) bytes.write(block,0,Math.min(n,640000-bytes.size()));
                else try { Thread.sleep(8); } catch(InterruptedException e) { cancel(); Thread.currentThread().interrupt(); }
            }
            return cancelled.get() ? new byte[0] : bytes.toByteArray();
        } finally {
            synchronized(this) {
                ended.set(true);
                try { input.stop(); } catch(IllegalStateException ignored) { }
                input.release(); recorder=null;
            }
        }
    }
}
