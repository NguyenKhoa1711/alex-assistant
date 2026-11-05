package vn.alex.phone;

/** One press owns one recording. Cancellation is terminal until the next press. */
final class VoiceGesture {
    private int pointer = -1;
    boolean begin(int id) { if (pointer != -1) return false; pointer = id; return true; }
    boolean active() { return pointer != -1; }
    boolean owns(int id) { return pointer == id && active(); }
    boolean release(int id) { if (!owns(id)) return false; pointer = -1; return true; }
    boolean cancel() { boolean was = active(); pointer = -1; return was; }
}
