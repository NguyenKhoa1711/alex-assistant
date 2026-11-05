package vn.alex.phone;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Offline tests only: no mic, app commands, PIN, SMS or network requests. */
public final class VoiceBehaviorLab {
    private static int checks;
    private static void check(boolean ok,String name) {
        if(!ok) throw new AssertionError(name);
        checks++; System.out.println("PASS "+name);
    }
    private static InputStream stream(String value) { return new ByteArrayInputStream(value.getBytes(StandardCharsets.UTF_8)); }
    public static void main(String[] args) throws Exception {
        VoiceGesture gesture=new VoiceGesture();
        check(gesture.begin(7),"press begins immediately");
        check(!gesture.begin(8),"second press cannot start another recording");
        check(!gesture.release(8),"other pointer cannot send");
        check(gesture.release(7),"release sends once");
        check(!gesture.release(7),"duplicate release cannot send twice");
        check(gesture.begin(7) && gesture.cancel(),"drag out or pause cancels current recording");
        check(!gesture.release(7),"release after cancel cannot send");
        check(!gesture.cancel(),"duplicate cancellation is harmless");
        check(gesture.begin(0) && gesture.release(0),"accessibility toggle has same single send semantics");
        System.out.println("RESULT "+checks+" gesture tests passed");
    }
}
