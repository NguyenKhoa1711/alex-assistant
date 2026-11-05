package vn.alex.phone;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.KeyguardManager;
import android.hardware.biometrics.BiometricManager;
import android.hardware.biometrics.BiometricPrompt;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothAdapter;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioTrack;
import android.media.MediaRecorder;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.CancellationSignal;
import android.os.SystemClock;
import android.provider.Settings;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.ByteArrayOutputStream;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final int PERMISSION = 10;
    private static final int VERIFY_PHONE = 11;
    private static final int SCAN_QR = 12;
    private static final int ENABLE_BT = 13;
    private static final int DISCOVERABLE_BT = 14;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private AlexConnection connection;
    private HidKeyboard keyboard;
    private BluetoothDevice chosenPc;
    private String verifiedPin;
    private final ExecutorService voiceWorker = Executors.newSingleThreadExecutor();
    private volatile VoiceCapture capture;
    private volatile boolean recording;
    private volatile boolean processingVoice;
    private volatile boolean visible;
    private boolean bluetoothReceiverRegistered;
    private TextView status, chatQuestion, chatAnswer, emptyChat, pcName, unlockStatus;
    private TextView connectionStatus, bluetoothSetupStatus;
    private TextView voiceBadge, bluetoothBadge, voiceTab, unlockTab, setupTab, alertTab;
    private EditText pairLink, windowsPin;
    private TalkButton recordButton;
    private LinearLayout voicePanel, unlockPanel, setupPanel, voiceNotice;
    private ScrollView scroll;
    private int selectedTab;
    private PetView pet;
    private final BroadcastReceiver bluetoothChanges = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (BluetoothAdapter.ACTION_STATE_CHANGED.equals(intent.getAction()) && bluetoothPermission()) {
                int state = intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, BluetoothAdapter.ERROR);
                if (state == BluetoothAdapter.STATE_ON) {
                    keyboard.start();
                    restorePc();
                    if (chosenPc != null) keyboard.prepare(chosenPc);
                }
                if (state == BluetoothAdapter.STATE_OFF) {
                    keyboard.stop();
                    unlockMessage("Bluetooth đang tắt trên điện thoại.");
                }
                syncConnectionUi();
            }
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        connection = new AlexConnection(this);
        keyboard = new HidKeyboard(this, text -> {
            unlockMessage(text);
            runOnUiThread(this::syncConnectionUi);
        });
        buildScreen();
        handleLink(getIntent());
    }

    @Override public void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleLink(intent);
    }

    @Override public void onResume() {
        super.onResume();
        visible = true;
        if (!bluetoothReceiverRegistered) {
            IntentFilter filter = new IntentFilter(BluetoothAdapter.ACTION_STATE_CHANGED);
            if (Build.VERSION.SDK_INT >= 33) registerReceiver(bluetoothChanges, filter, Context.RECEIVER_NOT_EXPORTED);
            else registerReceiver(bluetoothChanges, filter);
            bluetoothReceiverRegistered = true;
        }
        if (bluetoothPermission()) keyboard.start();
        restorePc();
        if (chosenPc != null) keyboard.prepare(chosenPc);
        sendVerifiedPin();
        syncConnectionUi();
    }

    @Override public void onPause() {
        visible = false;
        cancelRecording(false);
        if (bluetoothReceiverRegistered) {
            unregisterReceiver(bluetoothChanges);
            bluetoothReceiverRegistered = false;
        }
        keyboard.stop();
        super.onPause();
    }

    @Override public void onDestroy() {
        verifiedPin = null;
        cancelRecording(false);
        worker.shutdownNow();
        // Let an already queued capture enter its finally block and release the mic.
        voiceWorker.shutdown();
        super.onDestroy();
    }

    private void buildScreen() {
        LinearLayout root = UiKit.column(this);
        root.setBackgroundColor(UiKit.BACKGROUND);
        UiKit.window(this, root);
        setContentView(root);

        LinearLayout header = new LinearLayout(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(20),dp(12),dp(20),dp(12));
        TextView logo = UiKit.text(this, "a", 27, Color.WHITE, true);
        logo.setGravity(Gravity.CENTER); logo.setBackground(UiKit.shape(UiKit.PRIMARY,16,this));
        logo.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        header.addView(logo,new LinearLayout.LayoutParams(dp(46),dp(46)));
        LinearLayout brand = UiKit.column(this);
        brand.setPadding(dp(12),0,0,0);
        brand.addView(UiKit.text(this,"Alex",23,UiKit.INK,true));
        brand.addView(UiKit.text(this,getString(R.string.ui_assistant),12,UiKit.MUTED,false),UiKit.space(this,-1,-2,3,0));
        header.addView(brand,new LinearLayout.LayoutParams(0,-2,1));
        TextView version = UiKit.text(this,"1.8.1 · 23",12,UiKit.PRIMARY_DARK,true);
        version.setPadding(dp(10),dp(7),dp(10),dp(7));
        version.setBackground(UiKit.shape(UiKit.PALE,12,this));
        version.setContentDescription("Alex phiên bản 1.8.1"); header.addView(version);
        root.addView(header);

        scroll = new ScrollView(this);
        scroll.setFillViewport(true); scroll.setClipToPadding(false);
        root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        LinearLayout content = UiKit.column(this);
        content.setPadding(dp(18),dp(8),dp(18),dp(24)); scroll.addView(content);
        voicePanel = buildVoicePanel(); unlockPanel = buildUnlockPanel(); setupPanel = buildSetupPanel();
        content.addView(voicePanel); content.addView(unlockPanel); content.addView(setupPanel);

        LinearLayout navigation = new LinearLayout(this);
        navigation.setPadding(dp(8),dp(8),dp(8),dp(8)); navigation.setBackgroundColor(Color.WHITE);
        root.addView(navigation);
        voiceTab = navigationItem(getString(R.string.ui_chat),"chat",0,navigation);
        unlockTab = navigationItem(getString(R.string.ui_unlock),"lock",1,navigation);
        setupTab = navigationItem(getString(R.string.ui_connect),"link",2,navigation);
        alertTab = navigationItem(getString(R.string.ui_alert),"shield",3,navigation);
        alertTab.setTextColor(UiKit.DANGER);
        alertTab.setCompoundDrawables(null,UiKit.icon(this,"shield",UiKit.DANGER,22),null,null);
        alertTab.setOnClickListener(v -> startActivity(new Intent(this,AlertActivity.class)));
        showTab(0); syncConnectionUi();
    }

    private int dp(int value) { return UiKit.dp(this,value); }

    private TextView section(LinearLayout parent, int title, int subtitle) {
        TextView heading = UiKit.text(this,getString(title),25,UiKit.INK,true);
        parent.addView(heading,UiKit.space(this,-1,-2,4,7));
        parent.addView(UiKit.text(this,getString(subtitle),14,UiKit.MUTED,false),UiKit.space(this,-1,-2,0,20));
        return heading;
    }

    private LinearLayout buildVoicePanel() {
        LinearLayout panel = UiKit.column(this);
        voiceNotice = UiKit.card(this);
        voiceNotice.setBackground(UiKit.outline(Color.WHITE,UiKit.BORDER,22,this));
        voiceNotice.addView(UiKit.text(this,getString(R.string.ui_setup_title),16,UiKit.INK,true));
        voiceNotice.addView(UiKit.text(this,getString(R.string.ui_setup_hint),13,UiKit.MUTED,false),UiKit.space(this,-1,-2,5,10));
        voiceNotice.addView(UiKit.button(this,getString(R.string.ui_setup_action),false,v -> showTab(2)));
        panel.addView(voiceNotice,UiKit.space(this,-1,-2,0,14));

        LinearLayout card = UiKit.card(this);
        android.graphics.drawable.GradientDrawable gradient = new android.graphics.drawable.GradientDrawable(
                android.graphics.drawable.GradientDrawable.Orientation.TL_BR,new int[]{0xffe1f2ec,0xfff1f7f1});
        gradient.setCornerRadius(dp(28)); card.setBackground(gradient); card.setElevation(0);
        panel.addView(card,UiKit.space(this,-1,-2,0,22));
        TextView greeting = UiKit.text(this,getString(R.string.ui_greeting),23,UiKit.INK,true);
        greeting.setGravity(Gravity.CENTER); card.addView(greeting);
        TextView hint = UiKit.text(this,getString(R.string.ui_voice_hint),13,UiKit.MUTED,false);
        hint.setGravity(Gravity.CENTER); card.addView(hint,UiKit.space(this,-1,-2,6,0));
        pet = new PetView(this); card.addView(pet,UiKit.space(this,-1,dp(142),6,0));
        recordButton = new TalkButton(this);
        recordButton.setText(getString(R.string.ui_record));
        recordButton.setAllCaps(false); recordButton.setTextSize(15);
        recordButton.setTextColor(Color.WHITE);
        recordButton.setBackground(UiKit.ripple(this,UiKit.PRIMARY,false));
        recordButton.setPadding(dp(14),dp(10),dp(14),dp(10));
        recordButton.setSoundEffectsEnabled(false);
        recordButton.setListener(new TalkButton.Listener() {
            public boolean begin() { return beginRecording(); }
            public void release() { releaseRecording(); }
            public void cancel() { cancelRecording(true); }
        });
        recordButton.setCompoundDrawables(UiKit.icon(this,"mic",Color.WHITE,24),null,null,null);
        recordButton.setCompoundDrawablePadding(dp(12));
        recordButton.setMinimumHeight(dp(62)); card.addView(recordButton);
        TextView helper = UiKit.text(this,getString(R.string.ui_record_hint),12,UiKit.MUTED,false);
        helper.setGravity(Gravity.CENTER); card.addView(helper,UiKit.space(this,-1,-2,10,0));
        status = UiKit.text(this,"Kết nối PC để bắt đầu trò chuyện.",13,UiKit.PRIMARY_DARK,false);
        status.setGravity(Gravity.CENTER); status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        card.addView(status,UiKit.space(this,-1,-2,10,0));

        panel.addView(UiKit.text(this,getString(R.string.ui_recent),18,UiKit.INK,true),UiKit.space(this,-1,-2,0,12));
        LinearLayout history = UiKit.card(this); panel.addView(history);
        emptyChat = UiKit.text(this,getString(R.string.ui_empty),14,UiKit.MUTED,false);
        history.addView(emptyChat);
        chatQuestion = UiKit.text(this,"",15,UiKit.INK,false);
        chatQuestion.setPadding(dp(14),dp(12),dp(14),dp(12));
        chatQuestion.setBackground(UiKit.shape(UiKit.PALE,18,this));
        history.addView(chatQuestion,UiKit.space(this,-1,-2,0,12));
        chatAnswer = UiKit.text(this,"",15,UiKit.INK,false);
        chatAnswer.setPadding(dp(4),dp(4),dp(4),dp(4)); history.addView(chatAnswer);
        chatQuestion.setTextIsSelectable(true); chatAnswer.setTextIsSelectable(true);
        chatQuestion.setVisibility(View.GONE); chatAnswer.setVisibility(View.GONE);
        return panel;
    }

    private LinearLayout buildUnlockPanel() {
        LinearLayout panel = UiKit.column(this);
        section(panel,R.string.ui_unlock_title,R.string.ui_unlock_hint);
        panel.addView(RemoteAccessPanel.create(this),UiKit.space(this,-1,-2,0,20));
        LinearLayout nearby = UiKit.column(this);
        button("Dùng Bluetooth khi ở gần laptop",panel,v -> nearby.setVisibility(
            nearby.getVisibility()==View.VISIBLE ? View.GONE : View.VISIBLE));
        panel.addView(nearby); nearby.setVisibility(View.GONE);
        nearby.addView(UiKit.text(this,"Mở khóa gần laptop · Bluetooth",17,UiKit.INK,true),UiKit.space(this,-1,-2,12,12));
        LinearLayout device = UiKit.card(this); nearby.addView(device,UiKit.space(this,-1,-2,0,16));
        device.addView(UiKit.text(this,getString(R.string.ui_device),11,UiKit.MUTED,true));
        pcName = UiKit.text(this,"Chưa chọn máy tính",17,UiKit.INK,true);
        pcName.setCompoundDrawables(UiKit.icon(this,"link",UiKit.PRIMARY,26),null,null,null);
        pcName.setCompoundDrawablePadding(dp(12)); device.addView(pcName,UiKit.space(this,-1,-2,14,14));
        button("Chọn máy tính",device,v -> choosePc());
        LinearLayout card = UiKit.card(this); nearby.addView(card);
        card.addView(UiKit.text(this,getString(R.string.ui_pin),17,UiKit.INK,true));
        card.addView(UiKit.text(this,getString(R.string.ui_pin_hint),13,UiKit.MUTED,false),UiKit.space(this,-1,-2,6,16));
        windowsPin = new EditText(this); UiKit.field(windowsPin,"Nhập PIN của laptop");
        windowsPin.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_VARIATION_PASSWORD);
        windowsPin.setSingleLine(true); windowsPin.setSaveEnabled(false);
        windowsPin.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        card.addView(windowsPin,UiKit.space(this,-1,-2,0,16));
        button(getString(R.string.ui_unlock_action),card,v -> verifyAndUnlock());
        unlockStatus = UiKit.text(this,"Bật Bluetooth, chọn đúng PC rồi xác nhận trên điện thoại.",14,UiKit.MUTED,false);
        unlockStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        card.addView(unlockStatus,UiKit.space(this,-1,-2,8,0));
        return panel;
    }

    private LinearLayout buildSetupPanel() {
        LinearLayout panel = UiKit.column(this);
        section(panel,R.string.ui_connect_title,R.string.ui_connect_hint);
        LinearLayout badges = new LinearLayout(this);
        voiceBadge=badge("PC chưa ghép",badges); bluetoothBadge=badge("Bluetooth",badges);
        panel.addView(badges,UiKit.space(this,-1,-2,0,18));
        LinearLayout wifi = UiKit.card(this); panel.addView(wifi,UiKit.space(this,-1,-2,0,16));
        wifi.addView(UiKit.text(this,getString(R.string.ui_wifi_title),19,UiKit.INK,true));
        connectionStatus = UiKit.text(this,"",13,UiKit.PRIMARY_DARK,true);
        connectionStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        wifi.addView(connectionStatus,UiKit.space(this,-1,-2,6,12));
        wifi.addView(UiKit.text(this,getString(R.string.ui_wifi_hint),14,UiKit.MUTED,false),UiKit.space(this,-1,-2,0,16));
        Button qr=button(getString(R.string.ui_qr),wifi,v -> startActivityForResult(new Intent(this,QrScannerActivity.class),SCAN_QR));
        qr.setCompoundDrawables(UiKit.icon(this,"qr",Color.WHITE,22),null,null,null);
        LinearLayout manual = UiKit.column(this);
        pairLink = new EditText(this); UiKit.field(pairLink,"alexphone://pair?…");
        pairLink.setSingleLine(true); pairLink.setTextSize(13);
        pairLink.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        pairLink.setSaveEnabled(false); pairLink.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        manual.addView(pairLink,UiKit.space(this,-1,-2,4,10));
        button("Ghép bằng liên kết",manual,v -> pair(Uri.parse(pairLink.getText().toString().trim())));
        Button expand=button(getString(R.string.ui_manual),wifi,v -> manual.setVisibility(manual.getVisibility()==View.VISIBLE ? View.GONE : View.VISIBLE));
        wifi.addView(manual); manual.setVisibility(View.GONE);
        Button forget=button(getString(R.string.ui_forget),wifi,v -> new AlertDialog.Builder(this)
                .setTitle("Quên kết nối với PC?").setMessage("Bạn sẽ cần quét QR lại để trò chuyện. Ghép đôi Bluetooth vẫn được giữ.")
                .setNegativeButton("Giữ kết nối",null).setPositiveButton("Quên kết nối",(d,w) -> {
                    connection.forget(); syncConnectionUi(); connectionMessage("Đã quên kết nối giọng nói với PC.");
                    message("Kết nối PC để bắt đầu trò chuyện.");
                }).show());
        forget.setTextColor(UiKit.MUTED);

        LinearLayout bt=UiKit.card(this); panel.addView(bt);
        bt.addView(UiKit.text(this,getString(R.string.ui_bt_title),19,UiKit.INK,true));
        bt.addView(UiKit.text(this,getString(R.string.ui_bt_hint),14,UiKit.MUTED,false),UiKit.space(this,-1,-2,7,16));
        button(getString(R.string.ui_bt_on),bt,v -> openBluetooth());
        button(getString(R.string.ui_bt_visible),bt,v -> requestDiscoverable());
        button(getString(R.string.ui_bt_choose),bt,v -> choosePc());
        bluetoothSetupStatus=UiKit.text(this,"PIN chỉ dùng sau khi bạn xác nhận trên điện thoại.",13,UiKit.MUTED,false);
        bt.addView(bluetoothSetupStatus,UiKit.space(this,-1,-2,8,0));
        TextView privacy=UiKit.text(this,"Alex 1.8.1 · Thông tin ghép nối và ID laptop lưu trên thiết bị. Không lưu PIN Windows.",12,UiKit.MUTED,false);
        privacy.setGravity(Gravity.CENTER); panel.addView(privacy,UiKit.space(this,-1,-2,20,0));
        return panel;
    }

    private TextView badge(String title,LinearLayout parent) {
        TextView item=UiKit.text(this,title,12,UiKit.PRIMARY_DARK,true);
        item.setGravity(Gravity.CENTER); item.setPadding(dp(6),dp(10),dp(6),dp(10));
        item.setBackground(UiKit.shape(UiKit.PALE,14,this));
        LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(0,-2,1);
        params.leftMargin=dp(3); params.rightMargin=dp(3); parent.addView(item,params); return item;
    }

    private TextView navigationItem(String title,String icon,int tab,LinearLayout parent) {
        TextView item=UiKit.text(this,title,11,UiKit.MUTED,true);
        item.setGravity(Gravity.CENTER); item.setMinHeight(dp(62)); item.setPadding(dp(2),dp(8),dp(2),dp(8));
        item.setCompoundDrawables(null,UiKit.icon(this,icon,UiKit.MUTED,22),null,null);
        item.setCompoundDrawablePadding(dp(5)); item.setContentDescription(title);
        item.setOnClickListener(v -> showTab(tab));
        item.setBackground(UiKit.ripple(this,Color.WHITE,false));
        parent.addView(item,new LinearLayout.LayoutParams(0,-2,1)); return item;
    }

    private void showTab(int tab) {
        if (selectedTab != tab) cancelRecording(false);
        selectedTab=tab;
        voicePanel.setVisibility(tab==0 ? View.VISIBLE : View.GONE);
        unlockPanel.setVisibility(tab==1 ? View.VISIBLE : View.GONE);
        setupPanel.setVisibility(tab==2 ? View.VISIBLE : View.GONE);
        TextView[] items={voiceTab,unlockTab,setupTab}; String[] icons={"chat","lock","link"};
        for(int i=0;i<items.length;i++) {
            boolean chosen=i==tab; int color=chosen ? UiKit.PRIMARY_DARK : UiKit.MUTED;
            items[i].setTextColor(color); items[i].setSelected(chosen);
            items[i].setBackground(UiKit.ripple(this,chosen ? UiKit.PALE : Color.WHITE,false));
            items[i].setCompoundDrawables(null,UiKit.icon(this,icons[i],color,22),null,null);
        }
        scroll.post(() -> scroll.scrollTo(0,0));
    }

    @Override public void onBackPressed() {
        if (selectedTab != 0) showTab(0);
        else super.onBackPressed();
    }

    private void recordLabel(String text) {
        recordButton.setText(text);
        recordButton.setContentDescription(text);
        recordButton.setEnabled(recording || !processingVoice);
        recordButton.setAlpha(recordButton.isEnabled() ? 1f : .65f);
    }

    private void syncConnectionUi() {
        if(voiceBadge==null || bluetoothBadge==null) return;
        boolean paired=connection.isPaired();
        voiceBadge.setText(paired ? "PC · đã lưu ghép nối" : "PC · chưa ghép");
        voiceBadge.setBackground(UiKit.shape(paired ? UiKit.PALE : 0xffedf0ef,14,this));
        if(voiceNotice!=null) voiceNotice.setVisibility(paired ? View.GONE : View.VISIBLE);
        String bluetooth;
        if(!bluetoothPermission()) bluetooth="Bluetooth · cần quyền";
        else if(!keyboard.available()) bluetooth="Bluetooth · đang tắt";
        else if(chosenPc==null) bluetooth="Bluetooth · chọn PC";
        else if(keyboard.connectedTo(chosenPc)) bluetooth="Bluetooth · đã nối";
        else bluetooth="Bluetooth · đang nối";
        bluetoothBadge.setText(bluetooth);
        if(connectionStatus!=null && connectionStatus.getText().length()==0)
            connectionStatus.setText(paired ? "Đã lưu ghép nối. Không cần quét QR lại." : "Chưa ghép máy tính. Quét QR để bắt đầu.");
        if(status!=null && !recording && !processingVoice && chatQuestion.getText().length()==0)
            status.setText(paired ? "Ghép nối đã lưu · Bật Alex trên PC để trò chuyện." : "Kết nối PC để bắt đầu trò chuyện.");
    }

    private void openBluetooth() {
        if (!bluetoothPermission()) { askBluetoothPermissions(); return; }
        if (!keyboard.available()) {
            startActivityForResult(new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE), ENABLE_BT);
        } else {
            startActivity(new Intent(Settings.ACTION_BLUETOOTH_SETTINGS));
        }
    }

    private void requestDiscoverable() {
        if (!bluetoothPermission() || !bluetoothAdvertisePermission()) {
            askBluetoothPermissions();
            bluetoothSetupMessage("Cấp quyền Thiết bị ở gần rồi bấm lại để PC tìm thấy Alex.");
            return;
        }
        if (!keyboard.available()) { openBluetooth(); return; }
        Intent discover = new Intent(BluetoothAdapter.ACTION_REQUEST_DISCOVERABLE);
        discover.putExtra(BluetoothAdapter.EXTRA_DISCOVERABLE_DURATION, 120);
        startActivityForResult(discover, DISCOVERABLE_BT);
    }

    private Button button(String text, LinearLayout layout, View.OnClickListener click) {
        Button button = UiKit.button(this, text, layout == voicePanel || text.startsWith("Xác nhận")
                || text.startsWith("Quét QR") || text.startsWith("Bắt đầu"), click);
        layout.addView(button, UiKit.space(this, -1, -2, 0, 10));
        return button;
    }

    private void message(String text) {
        runOnUiThread(() -> { if (status != null) status.setText(text); });
    }

    private void unlockMessage(String text) {
        runOnUiThread(() -> { if (unlockStatus != null) unlockStatus.setText(text); });
    }

    private void connectionMessage(String text) {
        runOnUiThread(() -> { if (connectionStatus != null) connectionStatus.setText(text); });
    }

    private void bluetoothSetupMessage(String text) {
        runOnUiThread(() -> { if (bluetoothSetupStatus != null) bluetoothSetupStatus.setText(text); });
    }

    private void handleLink(Intent intent) {
        Uri data = intent == null ? null : intent.getData();
        if (data != null && "alexphone".equals(data.getScheme())) {
            showTab(2);
            pairLink.setText(data.toString());
            pair(data);
        }
    }

    private void pair(Uri link) {
        if (link == null || link.toString().trim().isEmpty()) {
            connectionMessage("Hãy quét QR hoặc dán liên kết ghép nối từ PC.");
            return;
        }
        pet.mode = 2; pet.invalidate();
        connectionMessage("Đang ghép nối với Alex trên PC…");
        worker.execute(() -> {
            try {
                connection.pair(link);
                runOnUiThread(() -> { pairLink.setText(""); showTab(0); });
                message("Đã ghép nối PC " + connection.host() + ". Bạn có thể nói chuyện.");
                connectionMessage("Đã ghép nối an toàn với PC.");
                runOnUiThread(this::syncConnectionUi);
            } catch (Exception error) { connectionMessage("Ghép nối lỗi: " + readableError(error)); }
            runOnUiThread(() -> { pet.mode = 0; pet.invalidate(); });
        });
    }

    private boolean bluetoothPermission() {
        return Build.VERSION.SDK_INT < 31 || checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED;
    }

    private boolean bluetoothAdvertisePermission() {
        return Build.VERSION.SDK_INT < 31 || checkSelfPermission(Manifest.permission.BLUETOOTH_ADVERTISE) == PackageManager.PERMISSION_GRANTED;
    }

    private void askBluetoothPermissions() {
        if (Build.VERSION.SDK_INT >= 31) {
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED
                    || checkSelfPermission(Manifest.permission.BLUETOOTH_ADVERTISE) != PackageManager.PERMISSION_GRANTED)
                requestPermissions(new String[]{Manifest.permission.BLUETOOTH_CONNECT,
                        Manifest.permission.BLUETOOTH_ADVERTISE}, PERMISSION);
        }
    }

    private void askAudioPermission() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, PERMISSION);
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (bluetoothPermission()) {
            keyboard.start();
            restorePc();
            if (chosenPc != null) keyboard.prepare(chosenPc);
        }
        syncConnectionUi();
        for (int i=0; i<permissions.length; i++) {
            if (Manifest.permission.RECORD_AUDIO.equals(permissions[i])) {
                message(i < results.length && results[i] == PackageManager.PERMISSION_GRANTED
                        ? "Đã có quyền mic. Giữ nút khi nói, nói xong thì thả tay."
                        : "Chưa có quyền mic. Vào Cài đặt điện thoại → Alex mới → Quyền → Mic để cho phép.");
            }
        }
    }

    private boolean beginRecording() {
        if (processingVoice || !visible) return false;
        if (!connection.isPaired()) {
            message("Hãy ghép nối Alex trên PC trước."); showTab(2); return false;
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            message("Cho phép Alex mới dùng mic, sau đó giữ nút để nói lại nhé.");
            askAudioPermission(); return false;
        }
        final VoiceCapture input = new VoiceCapture();
        try { input.start(); }
        catch (Exception error) { message("Lỗi mic: " + readableError(error)); return false; }
        capture = input; recording = true; processingVoice = true;
        pet.mode = 1; pet.invalidate();
        recordLabel("Thả để gửi"); message("Đang nghe bạn nói…");
        voiceWorker.execute(() -> {
            try {
                byte[] audio = input.read();
                runOnUiThread(() -> {
                    recording = false; recordButton.resetGesture();
                    if (visible && !input.cancelled()) {
                        pet.mode = 2; pet.invalidate(); recordLabel("Đang xử lý…");
                    }
                });
                if (!visible || input.cancelled()) return;
                if (audio.length < 3200) {
                    voiceMessage(input,"Bạn nói quá ngắn. Giữ nút khi nói, nói xong thì thả tay nhé.");
                    return;
                }
                // Keep the original /turn request, complete reply, and playback.
                AlexConnection.Turn turn = connection.sendVoice(audio);
                if (!visible || input.cancelled()) return;
                runOnUiThread(() -> { if (visible && !input.cancelled()) showTurn(turn); });
                if (turn.transcript.trim().isEmpty()) {
                    voiceMessage(input,"Alex chưa nghe rõ câu nói. Hãy nói gần mic hơn rồi thử lại.");
                } else {
                    if (turn.audio.length > 0) play(turn.audio, turn.sampleRate, input);
                    voiceMessage(input,"Alex đã trả lời.");
                }
            } catch (Exception error) {
                voiceMessage(input,"Alex chưa trả lời: " + readableError(error));
            } finally {
                runOnUiThread(() -> {
                    if (capture == input) capture = null;
                    recording = false; processingVoice = false;
                    if (!isFinishing()) {
                        pet.mode = 0; pet.invalidate(); recordButton.resetGesture();
                        recordLabel(getString(R.string.ui_record));
                    }
                });
            }
        });
        return true;
    }

    private void releaseRecording() {
        if (!recording) return;
        recording = false;
        VoiceCapture input = capture; if (input != null) input.release();
        recordLabel("Đang gửi câu hỏi…");
    }

    private void cancelRecording(boolean notify) {
        VoiceCapture input = capture; if (input != null) input.cancel();
        recording = false;
        if (recordButton != null) {
            recordButton.resetGesture(); recordLabel(getString(R.string.ui_record));
        }
        if (notify) message("Đã hủy thu âm. Giữ nút để nói lại.");
    }

    private void voiceMessage(VoiceCapture input, String text) {
        runOnUiThread(() -> { if (visible && !input.cancelled() && !isFinishing()) status.setText(text); });
    }

    private String readableError(Exception error) {
        if (error instanceof java.net.SocketTimeoutException || error instanceof java.net.ConnectException)
            return "Không tới được PC. Kiểm tra cùng Wi‑Fi và tường lửa trên PC.";
        String detail = error.getMessage();
        return detail == null || detail.trim().isEmpty() ? "Có lỗi kết nối, hãy thử lại." : detail;
    }

    private void showTurn(AlexConnection.Turn turn) {
        if (turn.transcript.trim().isEmpty()) return;
        emptyChat.setVisibility(View.GONE);
        chatQuestion.setText("Bạn  ·  " + turn.transcript);
        chatAnswer.setText("Alex  ·  " + turn.reply);
        chatQuestion.setVisibility(View.VISIBLE);
        chatAnswer.setVisibility(View.VISIBLE);
        showTab(0);
    }

    private void play(byte[] audio, int rate, VoiceCapture input) {
        if (rate < 8000 || rate > 48000) return;
        int minimum = AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT);
        if (minimum <= 0) return;
        AudioTrack track = new AudioTrack(AudioManager.STREAM_MUSIC, rate,
                AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT,
                Math.max(minimum, 8192), AudioTrack.MODE_STREAM);
        try {
            runOnUiThread(() -> { if (visible && !input.cancelled()) { pet.mode = 3; pet.invalidate(); } });
            track.play();
            for (int offset = 0; offset < audio.length && visible && !input.cancelled();) {
                int n = track.write(audio, offset, Math.min(8192, audio.length - offset));
                if (n <= 0) break;
                offset += n;
            }
            long deadline = System.currentTimeMillis() + Math.min((long) audio.length * 1000 / (rate * 2) + 5000, 90000);
            while (visible && !input.cancelled() && track.getPlaybackHeadPosition() < audio.length / 2 && System.currentTimeMillis() < deadline)
                Thread.sleep(25);
        } catch (Exception ignored) { }
        finally { track.stop(); track.release(); }
    }

    private void choosePc() {
        if (!bluetoothPermission()) { askBluetoothPermissions(); return; }
        List<BluetoothDevice> devices = keyboard.pairedComputers();
        if (devices.isEmpty()) { bluetoothSetupMessage("Chưa có PC Bluetooth ghép đôi. Hãy ghép đôi trong cài đặt Windows."); showTab(2); return; }
        String[] names = new String[devices.size()];
        for (int i = 0; i < devices.size(); i++) {
            String name = devices.get(i).getName();
            names[i] = (name == null ? "Không tên" : name) + " · " + devices.get(i).getAddress();
        }
        new AlertDialog.Builder(this).setTitle("Chọn PC Windows đã ghép đôi")
                .setItems(names, (dialog, which) -> {
                    chosenPc = devices.get(which);
                    getSharedPreferences("bluetooth_pc", MODE_PRIVATE).edit()
                            .putString("address", chosenPc.getAddress()).apply();
                    pcName.setText("PC: " + names[which]);
                    keyboard.prepare(chosenPc);
                    bluetoothSetupMessage("Đã chọn " + names[which] + ".");
                    syncConnectionUi();
                }).show();
    }

    private void restorePc() {
        if (!bluetoothPermission()) return;
        String address = getSharedPreferences("bluetooth_pc", MODE_PRIVATE).getString("address", "");
        for (BluetoothDevice device : keyboard.pairedComputers()) {
            if (device.getAddress().equals(address)) {
                chosenPc = device;
                String name = device.getName();
                pcName.setText("PC: " + (name == null ? "Không tên" : name) + " · " + address);
                return;
            }
        }
        chosenPc = null;
        pcName.setText("Chưa chọn PC Bluetooth");
    }

    private void verifyAndUnlock() {
        if (chosenPc == null) { unlockMessage("Hãy chọn PC Bluetooth đã ghép đôi."); return; }
        String pin = windowsPin.getText().toString();
        if (!pin.matches("[0-9]{4,20}")) { unlockMessage("Nhập PIN Windows bằng 4 đến 20 chữ số."); return; }
        KeyguardManager keyguard = (KeyguardManager) getSystemService(Context.KEYGUARD_SERVICE);
        if (keyguard == null || !keyguard.isDeviceSecure()) {
            unlockMessage("Điện thoại cần có khóa màn hình trước khi dùng tính năng mở khóa PC."); return;
        }
        unlockMessage("Đang xác nhận khóa màn hình OPPO…");
        if (Build.VERSION.SDK_INT >= 29) {
            try {
                BiometricPrompt.Builder builder = new BiometricPrompt.Builder(this)
                        .setTitle("Alex mở khóa Windows")
                        .setSubtitle("Xác nhận trên OPPO trước khi nhập PIN vào PC");
                if (Build.VERSION.SDK_INT >= 30) {
                    builder.setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG
                            | BiometricManager.Authenticators.DEVICE_CREDENTIAL);
                } else {
                    builder.setDeviceCredentialAllowed(true);
                }
                builder.build().authenticate(new CancellationSignal(), getMainExecutor(),
                        new BiometricPrompt.AuthenticationCallback() {
                    @Override public void onAuthenticationSucceeded(BiometricPrompt.AuthenticationResult result) {
                        onPhoneVerified();
                    }
                    @Override public void onAuthenticationError(int code, CharSequence error) {
                        windowsPin.setText("");
                        unlockMessage("Chưa xác nhận được trên OPPO: " + error);
                    }
                });
                return;
            } catch (RuntimeException error) {
                unlockMessage("Dùng xác nhận khóa màn hình OPPO…");
            }
        }
        Intent verify = keyguard.createConfirmDeviceCredentialIntent("Alex mở khóa Windows",
                "Xác nhận trên điện thoại trước khi nhập PIN vào PC");
        if (verify == null) { unlockMessage("Không mở được xác nhận khóa màn hình điện thoại."); return; }
        startActivityForResult(verify, VERIFY_PHONE);
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == SCAN_QR) {
            if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                pairLink.setText(data.getData().toString());
                pair(data.getData());
            }
            return;
        }
        if (requestCode == ENABLE_BT) {
            if (resultCode == RESULT_OK) {
                keyboard.start();
                restorePc();
                if (chosenPc != null) keyboard.prepare(chosenPc);
            }
            syncConnectionUi();
            return;
        }
        if (requestCode == DISCOVERABLE_BT) {
            bluetoothSetupMessage(resultCode > 0 ? "Alex đang cho PC tìm thấy trong 2 phút. Ghép OPPO trên Windows ngay."
                    : "Bạn đã hủy chế độ cho PC tìm thấy Alex.");
            return;
        }
        if (requestCode != VERIFY_PHONE) return;
        if (resultCode != RESULT_OK) { windowsPin.setText(""); unlockMessage("Đã hủy mở khóa PC."); return; }
        onPhoneVerified();
    }

    private void onPhoneVerified() {
        String pin = windowsPin.getText().toString();
        windowsPin.setText("");
        verifiedPin = pin;
        unlockMessage("Đã xác nhận trên OPPO; đang nối bàn phím với Windows…");
        sendVerifiedPin();
    }

    private void sendVerifiedPin() {
        if (!visible || verifiedPin == null || chosenPc == null) return;
        String pin = verifiedPin;
        verifiedPin = null;
        keyboard.unlock(chosenPc, pin);
    }

    private static final class PetView extends View {
        int mode = 0;
        final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        PetView(Context context) {
            super(context);
            setLayerType(View.LAYER_TYPE_SOFTWARE, null);
            setContentDescription("Alex, thú cưng trợ lý ảo");
        }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float x = getWidth() / 2f;
            float r = Math.min(getWidth(), getHeight()) * .35f;
            double tick = SystemClock.uptimeMillis() / 420.0;
            float y = getHeight() / 2f + (float) Math.sin(tick * .42) * r * .045f;
            int[] colors = {0xff75d8d8, 0xff69e3b4, 0xffffd079, 0xffb9a3f8};
            paint.setShader(null);
            paint.setColor(mode == 0 ? 0x337bded8 : 0x55ffffff);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(UiKit.dp(getContext(), 2));
            float pulse = mode == 0 ? 1.15f : 1.16f + (float) Math.sin(tick * 1.5) * .065f;
            canvas.drawCircle(x, y, r * pulse, paint);
            paint.setStyle(Paint.Style.FILL);
            paint.setShader(new RadialGradient(x-r*.24f, y-r*.36f, r*1.8f,
                    new int[]{0xffe2ffff, colors[mode], colors[mode]},
                    null, Shader.TileMode.CLAMP));
            paint.setShadowLayer(UiKit.dp(getContext(), 8), 0, UiKit.dp(getContext(), 5), 0x55000000);
            canvas.drawCircle(x, y, r, paint);
            paint.clearShadowLayer();
            paint.setShader(null);
            paint.setColor(0x55ffffff);
            canvas.drawCircle(x-r*.4f, y-r*.55f, r*.17f, paint);
            paint.setColor(0xff18394a);
            canvas.drawCircle(x-r*.32f, y-r*.13f, r*.085f, paint);
            canvas.drawCircle(x+r*.32f, y-r*.13f, r*.085f, paint);
            if (mode == 1 || mode == 3) {
                paint.setStyle(Paint.Style.STROKE);
                paint.setStrokeWidth(UiKit.dp(getContext(), 3));
                canvas.drawCircle(x, y+r*.29f, r*(mode == 3 ? .17f : .11f), paint);
            } else if (mode == 2) {
                paint.setStrokeWidth(UiKit.dp(getContext(), 3));
                canvas.drawRoundRect(x-r*.19f, y+r*.22f, x+r*.19f, y+r*.27f,
                        UiKit.dp(getContext(), 2), UiKit.dp(getContext(), 2), paint);
            } else {
                paint.setStyle(Paint.Style.STROKE);
                paint.setStrokeWidth(UiKit.dp(getContext(), 3));
                canvas.drawArc(x-r*.26f, y+r*.06f, x+r*.26f, y+r*.45f,
                        10, 160, false, paint);
            }
            if (mode == 2) {
                paint.setStyle(Paint.Style.FILL);
                for (int index = 0; index < 3; index++) {
                    float angle = (float) (tick * .8 + index * Math.PI * 2 / 3);
                    paint.setColor(0xffd5f8f5);
                    canvas.drawCircle(x+(float)Math.cos(angle)*r*1.34f,
                            y+(float)Math.sin(angle)*r*1.34f, r*.065f, paint);
                }
            }
            paint.setShader(null);
            paint.setStyle(Paint.Style.FILL);
            if (isShown() && hasWindowFocus()) postInvalidateDelayed(mode == 0 ? 160 : 80);
        }
    }
}
