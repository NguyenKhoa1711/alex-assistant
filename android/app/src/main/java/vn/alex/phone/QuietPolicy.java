package vn.alex.phone;

/** Audio changes are isolated from alert dispatch and can be tested without sending. */
final class QuietPolicy {
    static final int[] STREAMS = {3, 2, 5, 4, 1, 8}; // Music, ring, notification, alarm, system, keypad.
    interface Audio {
        int volume(int stream);
        void volume(int stream, int value);
        int ringer();
        void ringer(int value);
        int filter();
        void filter(int value);
        boolean permission();
        boolean ownRule();
    }
    interface Journal {
        Snapshot load();
        boolean save(Snapshot snapshot);
        boolean clear();
    }
    static final class Snapshot {
        final int[] volumes;
        final int ringer, filter;
        Snapshot(int[] volumes, int ringer, int filter) {
            this.volumes = volumes.clone(); this.ringer = ringer; this.filter = filter;
        }
    }
    private final Audio audio;
    private final Journal journal;
    QuietPolicy(Audio audio, Journal journal) { this.audio = audio; this.journal = journal; }
    boolean active() { return journal.load() != null; }
    boolean silence() {
        try {
            if (!active()) {
                int[] volumes = new int[STREAMS.length];
                for (int i = 0; i < STREAMS.length; i++) volumes[i] = audio.volume(STREAMS[i]);
                if (!journal.save(new Snapshot(volumes, audio.ringer(), audio.filter()))) return false;
            }
        } catch (RuntimeException ex) { return false; }
        boolean complete = true;
        // Each stream is independent: one denied setting must not skip the others.
        for (int stream : STREAMS) {
            try { audio.volume(stream, 0); } catch (RuntimeException ex) { complete = false; }
        }
        try { audio.ringer(0); } catch (RuntimeException ex) { complete = false; }
        try {
            if (audio.permission()) audio.filter(3); // INTERRUPTION_FILTER_NONE
            else complete = false;
        } catch (RuntimeException ex) { complete = false; }
        return complete && quiet();
    }
    boolean quiet() {
        try {
            for (int stream : STREAMS) if (audio.volume(stream) != 0) return false;
            return audio.ringer() == 0 && audio.filter() == 3;
        } catch (RuntimeException ex) { return false; }
    }
    // Only called by the user's explicit Restore action, never by cancel/end/resume.
    boolean restore() {
        Snapshot saved = journal.load();
        if (saved == null) return true;
        boolean complete = true;
        // Release our DND request before restoring volumes; other apps' rules remain.
        try {
            if (audio.permission()) audio.filter(audio.ownRule() ? 1 : saved.filter);
            else if (audio.filter() != saved.filter) complete = false;
        } catch (RuntimeException ex) { complete = false; }
        for (int i = 0; i < STREAMS.length; i++) {
            try { audio.volume(STREAMS[i], saved.volumes[i]); } catch (RuntimeException ex) { complete = false; }
        }
        try { audio.ringer(saved.ringer); } catch (RuntimeException ex) { complete = false; }
        // Ringer changes can also affect DND on older Android versions.
        try {
            if (audio.permission()) audio.filter(audio.ownRule() ? 1 : saved.filter);
        } catch (RuntimeException ex) { complete = false; }
        return complete && journal.clear();
    }
}
