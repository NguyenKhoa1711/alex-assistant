package vn.alex.phone;

final class QuietPolicyTests {
    static void check(boolean value, String message) { AlertPolicyTests.check(value, message); }
    static final class Memory implements QuietPolicy.Journal {
        QuietPolicy.Snapshot saved;
        boolean writable = true;
        public QuietPolicy.Snapshot load() { return saved; }
        public boolean save(QuietPolicy.Snapshot value) { if (!writable) return false; saved = value; return true; }
        public boolean clear() { saved = null; return true; }
    }
    static final class Audio implements QuietPolicy.Audio {
        final int[] volumes = {0, 3, 5, 9, 7, 5, 0, 0, 4};
        int ringer = 2, filter = 1, blocked = -1, mutations;
        boolean permission = true, modern;
        public int volume(int stream) { return volumes[stream]; }
        public void volume(int stream, int value) {
            if (stream == blocked) throw new SecurityException();
            mutations++; volumes[stream] = value;
        }
        public int ringer() { return ringer; }
        public void ringer(int value) { mutations++; ringer = value; }
        public int filter() { return filter; }
        public void filter(int value) { if (!permission) throw new SecurityException(); mutations++; filter = value; }
        public boolean permission() { return permission; }
        public boolean ownRule() { return modern; }
    }
    static void run() {
        Audio audio = new Audio(); Memory memory = new Memory();
        QuietPolicy policy = new QuietPolicy(audio, memory);
        check(!policy.active(), "audio unchanged until explicit request");
        check(policy.silence(), "all supported streams quiet");
        check(audio.ringer == 0 && audio.filter == 3, "no vibrate, no interruptions");
        for (int stream : QuietPolicy.STREAMS) check(audio.volumes[stream] == 0, "zero volume " + stream);
        QuietPolicy.Snapshot original = memory.saved;
        check(policy.silence() && original == memory.saved, "duplicate activation preserves original sound");
        QuietPolicy reopened = new QuietPolicy(audio, memory);
        check(reopened.active() && audio.ringer == 0, "reopening does not restore sound");
        check(reopened.restore() && !reopened.active(), "explicit restore clears journal");
        check(audio.volumes[3] == 9 && audio.volumes[4] == 7 && audio.ringer == 2 && audio.filter == 1, "restore original volumes and modes");
        int mutations = audio.mutations;
        check(reopened.restore() && audio.mutations == mutations, "restore without snapshot does nothing");
        memory.writable = false;
        check(!policy.silence() && audio.mutations == mutations, "journal failure reported without losing restore state");
        memory.writable = true; audio.permission = false;
        check(!policy.silence() && policy.active(), "missing DND access is partial, never success");
        check(audio.volumes[3] == 0 && audio.volumes[4] == 0, "missing permission still attempts media and alarm mute");
        audio.permission = true; policy.restore();
        audio.blocked = 3;
        check(!policy.silence() && audio.volumes[4] == 0, "one rejected stream does not skip others");
        check(!policy.restore() && policy.active(), "failed restore retains original snapshot");
        audio.blocked = -1;
        check(policy.restore() && audio.volumes[3] == 9, "restore retry retains original volume");
        audio.modern = true; audio.filter = 2;
        policy.silence(); policy.restore();
        check(audio.filter == 1, "Android35 deactivates only own DND request");
        AlertPlan mid = new AlertPlan(2);
        check(AlertRoute.next(mid, false, false, false) == AlertRoute.MESSAGE, "level2 call request works without GPS");
        check(AlertRoute.next(mid, true, false, true) == AlertRoute.LOCATION, "level2 follows text with journey");
        check(AlertRoute.next(mid, true, true, true) == AlertRoute.DONE, "claimed work never repeated");
        check(AlertRoute.next(mid, false, true, true) == AlertRoute.MESSAGE, "level1 to level2 still sends call request");
        check(AlertRoute.next(new AlertPlan(1), false, false, true) == AlertRoute.LOCATION, "level1 never sends text");
    }
}
