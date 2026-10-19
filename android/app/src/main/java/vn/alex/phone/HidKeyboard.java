package vn.alex.phone;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothHidDevice;
import android.bluetooth.BluetoothHidDeviceAppSdpSettings;
import android.bluetooth.BluetoothProfile;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

final class HidKeyboard {
    interface Listener { void status(String message); }

    private static final long HID_SETTLE_MS = 800;
    private static final long WINDOWS_WAKE_MS = 1400;
    private static final long PIN_FIELD_MS = 600;

    private static final byte[] DESCRIPTOR = new byte[] {
        0x05, 0x01, 0x09, 0x06, (byte)0xA1, 0x01,
        0x05, 0x07, 0x19, (byte)0xE0, 0x29, (byte)0xE7,
        0x15, 0x00, 0x25, 0x01, 0x75, 0x01, (byte)0x95, 0x08, (byte)0x81, 0x02,
        (byte)0x95, 0x01, 0x75, 0x08, (byte)0x81, 0x03,
        (byte)0x95, 0x05, 0x75, 0x01, 0x05, 0x08, 0x19, 0x01, 0x29, 0x05, (byte)0x91, 0x02,
        (byte)0x95, 0x01, 0x75, 0x03, (byte)0x91, 0x03,
        (byte)0x95, 0x06, 0x75, 0x08, 0x15, 0x00, 0x25, 0x65,
        0x05, 0x07, 0x19, 0x00, 0x29, 0x65, (byte)0x81, 0x00, (byte)0xC0
    };

    private final Context context;
    private final Listener listener;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final BluetoothAdapter adapter = BluetoothAdapter.getDefaultAdapter();
    private final AtomicBoolean sending = new AtomicBoolean();
    private volatile BluetoothHidDevice hid;
    private volatile BluetoothDevice connected;
    private volatile long connectedAtMs;
    private BluetoothDevice target;
    private String pendingPin;
    private boolean registered;
    private boolean started;

    HidKeyboard(Context context, Listener listener) {
        this.context = context;
        this.listener = listener;
    }

    boolean available() { return adapter != null && adapter.isEnabled(); }

    boolean connectedTo(BluetoothDevice computer) {
        return computer != null && computer.equals(connected);
    }

    List<BluetoothDevice> pairedComputers() {
        return adapter == null ? new ArrayList<>() : new ArrayList<>(adapter.getBondedDevices());
    }

    void start() {
        if (started) return;
        if (!available()) { status("Bật Bluetooth trên điện thoại để kiểm tra HID."); return; }
        started = true;
        boolean requested = adapter.getProfileProxy(context, new BluetoothProfile.ServiceListener() {
            @Override public void onServiceConnected(int profile, BluetoothProfile proxy) {
                if (!(proxy instanceof BluetoothHidDevice)) {
                    status("Máy OPPO không cung cấp Bluetooth HID Device."); return;
                }
                hid = (BluetoothHidDevice) proxy;
                BluetoothHidDeviceAppSdpSettings sdp = new BluetoothHidDeviceAppSdpSettings(
                        "Alex Keyboard", "Nhập PIN Windows từ điện thoại", "Alex",
                        BluetoothHidDevice.SUBCLASS1_KEYBOARD, DESCRIPTOR);
                boolean requested = hid.registerApp(sdp, null, null, context.getMainExecutor(),
                        new BluetoothHidDevice.Callback() {
                    @Override public void onAppStatusChanged(BluetoothDevice pluggedDevice, boolean ok) {
                        registered = ok;
                        status(ok ? "Bàn phím Bluetooth đã sẵn sàng. Chọn máy tính đã ghép đôi."
                                : "Bluetooth HID không đăng ký được trên điện thoại này.");
                        if (ok && target != null) connectPending();
                        if (!ok) pendingPin = null;
                    }
                    @Override public void onConnectionStateChanged(BluetoothDevice device, int state) {
                        if (state == BluetoothProfile.STATE_CONNECTED) {
                            connected = device;
                            connectedAtMs = SystemClock.elapsedRealtime();
                            status("Đã kết nối bàn phím với " + device.getName());
                            if (pendingPin != null && device.equals(target)) sendPending();
                        } else if (state == BluetoothProfile.STATE_DISCONNECTED) {
                            connected = null;
                            status("Bàn phím Bluetooth đã ngắt kết nối.");
                        }
                    }
                });
                if (!requested) status("Máy OPPO từ chối đăng ký Bluetooth HID Device.");
            }
            @Override public void onServiceDisconnected(int profile) {
                hid = null; registered = false; connected = null;
                status("Dịch vụ bàn phím Bluetooth đã dừng.");
            }
        }, BluetoothProfile.HID_DEVICE);
        if (!requested) {
            started = false;
            status("Android không mở được dịch vụ Bluetooth HID Device.");
        }
    }

    void stop() {
        pendingPin = null;
        if (hid != null) {
            try { hid.unregisterApp(); } catch (Exception ignored) { }
            adapter.closeProfileProxy(BluetoothProfile.HID_DEVICE, hid);
        }
        hid = null; connected = null; registered = false;
        started = false;
    }

    void unlock(BluetoothDevice computer, String pin) {
        if (pin == null || !pin.matches("[0-9]{4,20}")) {
            status("Nhập PIN Windows bằng 4 đến 20 chữ số."); return;
        }
        if (sending.get()) { status("Alex đang nhập PIN; hãy chờ Windows phản hồi."); return; }
        target = computer;
        pendingPin = pin;
        if (!registered || hid == null) {
            status("Đang bật bàn phím Bluetooth để nhập PIN…");
            start();
            return;
        }
        connectPending();
    }

    void prepare(BluetoothDevice computer) {
        target = computer;
        if (!registered || hid == null) {
            start();
            return;
        }
        connectPending();
    }

    private void connectPending() {
        BluetoothDevice computer = target;
        if (computer.equals(connected)) { sendPending(); return; }
        status("Đang nối bàn phím Bluetooth với Windows…");
        if (!hid.connect(computer)) {
            pendingPin = null;
            status("Không nối được bàn phím. Hãy ghép đôi điện thoại với PC khi Windows đang mở.");
        } else {
            main.postDelayed(() -> {
                if (connected == null && computer.equals(target)) {
                    pendingPin = null;
                    status("Hết thời gian kết nối Bluetooth. Hãy kiểm tra ghép đôi trên Windows.");
                }
            }, 12000);
        }
    }

    private void sendPending() {
        final String pin = pendingPin;
        final BluetoothDevice computer = target;
        pendingPin = null;
        if (pin == null || computer == null) return;
        if (!sending.compareAndSet(false, true)) {
            status("Alex đang nhập PIN; hãy chờ Windows phản hồi.");
            return;
        }
        new Thread(() -> {
            try {
                // A newly connected HID keyboard needs time to become usable.
                Thread.sleep(Math.max(0, HID_SETTLE_MS -
                        (SystemClock.elapsedRealtime() - connectedAtMs)));
                status("Đang đánh thức màn hình Windows…");
                key(computer, (byte)0x2c);
                // The first Space may only wake a sleeping laptop. Give Windows
                // time to resume, then dismiss the lock-screen curtain.
                Thread.sleep(WINDOWS_WAKE_MS);
                key(computer, (byte)0x2c);
                status("Đang chờ ô nhập PIN Windows…");
                Thread.sleep(PIN_FIELD_MS);
                for (char digit : pin.toCharArray()) {
                    key(computer, (byte)(digit == '0' ? 0x27 : 0x1e + digit - '1'));
                    Thread.sleep(110);
                }
                key(computer, (byte)0x28); // Windows verifies the PIN; Alex cannot bypass it.
                status("Đã nhập PIN qua Bluetooth. Kiểm tra màn hình Windows.");
            } catch (Exception error) { status("Gửi PIN qua Bluetooth thất bại: " + error.getMessage()); }
            finally { sending.set(false); }
        }, "alex-hid-pin").start();
    }

    private void key(BluetoothDevice computer, byte code) throws InterruptedException {
        if (hid == null || !computer.equals(connected))
            throw new IllegalStateException("Mất kết nối bàn phím với PC đã chọn.");
        byte[] report = new byte[8];
        report[2] = code;
        if (!hid.sendReport(computer, 0, report)) throw new IllegalStateException("Windows không nhận phím.");
        Thread.sleep(70);
        if (!hid.sendReport(computer, 0, new byte[8])) throw new IllegalStateException("Windows không nhận thả phím.");
    }

    private void status(String message) { main.post(() -> listener.status(message)); }
}
