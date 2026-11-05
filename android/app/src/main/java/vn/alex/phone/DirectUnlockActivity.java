package vn.alex.phone;

import android.app.Activity;
import android.app.KeyguardManager;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.SystemClock;
import android.text.InputFilter;
import android.text.InputType;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.util.Arrays;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** PIN lives only in this screen's temporary buffers. No intents, preferences or saved state. */
public final class DirectUnlockActivity extends Activity {
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private final Handler handler=new Handler(android.os.Looper.getMainLooper());
    private AlexConnection connection;
    private EditText pin;
    private TextView status;
    private Button unlock,check;
    private UnlockAttempt attempt;
    private int nextRequestCode=71;
    private String laptopStatus="unavailable";
    private boolean authenticating,busy,destroyed;
    private Runnable expire;

    @Override public void onCreate(Bundle state) {
        super.onCreate(null);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        connection=new AlexConnection(this);
        LinearLayout outer=UiKit.column(this); UiKit.window(this,outer);
        ScrollView scroll=new ScrollView(this); LinearLayout content=UiKit.column(this);
        int pad=UiKit.dp(this,22); content.setPadding(pad,pad,pad,pad);
        scroll.addView(content); outer.addView(scroll); setContentView(outer);
        content.addView(UiKit.button(this,"‹ Quay lại",false,v->finish()));
        content.addView(UiKit.text(this,"Mở khóa laptop",27,UiKit.INK,true),UiKit.space(this,-1,-2,24,12));
        content.addView(UiKit.text(this,"Nhập PIN Windows Hello, xác nhận khóa màn hình OPPO rồi gửi một lần. PIN không được lưu.",15,UiKit.MUTED,false));
        LinearLayout card=UiKit.card(this); content.addView(card,UiKit.space(this,-1,-2,24,16));
        card.addView(UiKit.text(this,connection.isPaired()?"Laptop đã ghép với Alex":"Chưa ghép laptop",17,UiKit.INK,true));
        card.addView(UiKit.text(this,PrivateAddress.remote(connection.host())?"Qua mạng riêng · dùng được khác Wi-Fi":"Kết nối Wi-Fi đã lưu · Internet cần thiết lập mạng riêng",13,UiKit.MUTED,false),UiKit.space(this,-1,-2,8,16));
        pin=new EditText(this); UiKit.field(pin,"PIN Windows Hello");
        pin.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_VARIATION_PASSWORD);
        pin.setSingleLine(true); pin.setFilters(new InputFilter[]{new InputFilter.LengthFilter(20)});
        pin.setSaveEnabled(false); pin.setSaveFromParentEnabled(false);
        pin.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        pin.setImeOptions(EditorInfo.IME_ACTION_DONE | EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING);
        card.addView(pin);
        unlock=UiKit.button(this,"Mở khóa ngay",true,v->verifyPhone());
        card.addView(unlock,UiKit.space(this,-1,-2,16,12));
        status=UiKit.text(this,"Kiểm tra laptop trước khi nhập PIN.",14,UiKit.MUTED,false);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE); card.addView(status);
        check=UiKit.button(this,"Kiểm tra laptop",false,v->probe()); content.addView(check);
        content.addView(UiKit.text(this,"Laptop cần đang thức, đã đăng nhập Windows ít nhất một lần và Alex đang chạy. Bản này chưa bật máy tắt nguồn hoặc đánh thức từ Sleep.",13,UiKit.MUTED,false),UiKit.space(this,-1,-2,20,10));
        content.addView(UiKit.text(this,"Dùng ngoài nhà: thiết lập Tailscale một lần trên hai máy, rồi ghép QR mạng riêng từ laptop. Những lần sau mở khóa ngay ở màn hình này.",13,UiKit.MUTED,false));
        probe();
    }
    private void setBusy(boolean value) {
        busy=value;
        boolean ready=UnlockAttempt.canStart(connection.isPaired(),laptopStatus,busy);
        unlock.setEnabled(ready); pin.setEnabled(ready); check.setEnabled(!value);
    }
    private void show(String text) { if(!destroyed) status.setText(text); }
    private void probe() {
        if(busy || destroyed) return; laptopStatus="unavailable"; setBusy(true); show("Đang kiểm tra laptop…");
        worker.execute(()->{
            String code;
            try { code=connection.unlockStatus().optString("status"); } catch(Exception ignored) { code="offline"; }
            final String result=code;
            runOnUiThread(()->{ if(!destroyed) { laptopStatus=result; show(message(result)); setBusy(false); } });
        });
    }
    private void verifyPhone() {
        if(destroyed || !UnlockAttempt.canStart(connection.isPaired(),laptopStatus,busy)) return;
        if(nextRequestCode>65535) { show("Bạn đóng rồi mở lại màn hình Mở khóa để tiếp tục."); return; }
        int length=pin.length();
        if(length<4 || length>20) { pin.setError("Nhập PIN từ 4 đến 20 chữ số."); return; }
        cancelAttempt(); byte[] digits=new byte[length];
        for(int i=0;i<length;i++) {
            char digit=pin.getText().charAt(i);
            if(digit<'0' || digit>'9') { Arrays.fill(digits,(byte)0); pin.setError("PIN chỉ gồm chữ số."); return; }
            digits[i]=(byte)digit;
        }
        pin.getText().clear();
        final UnlockAttempt current=new UnlockAttempt(nextRequestCode++,digits,SystemClock.elapsedRealtime());
        attempt=current;
        KeyguardManager manager=(KeyguardManager)getSystemService(KEYGUARD_SERVICE);
        if(manager==null || !manager.isDeviceSecure()) { cancelAttempt(); show("Bạn cần đặt khóa màn hình OPPO để xác nhận mở khóa laptop."); return; }
        Intent intent=manager.createConfirmDeviceCredentialIntent("Mở khóa laptop bằng Alex","Xác nhận trên OPPO để gửi PIN Windows một lần.");
        if(intent==null) { cancelAttempt(); show("OPPO chưa mở được xác nhận khóa màn hình."); return; }
        authenticating=true; laptopStatus="unavailable"; setBusy(true);
        expire=()->{
            if(attempt!=current || destroyed || !current.expire(SystemClock.elapsedRealtime())) return;
            authenticating=false; setBusy(false);
            show("Phiên xác nhận đã hết hạn. Không gửi PIN. Bấm Kiểm tra laptop để thử lại.");
        };
        handler.postDelayed(expire,UnlockAttempt.AUTH_TIMEOUT_MS);
        try { startActivityForResult(intent,current.requestCode); }
        catch(Exception ignored) { authenticating=false; removeExpiry(); cancelAttempt(); setBusy(false); show("Không mở được xác nhận trên OPPO."); }
    }
    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);
        final UnlockAttempt current=attempt;
        if(destroyed || current==null || request!=current.requestCode || current.wasClaimed()) return;
        removeExpiry(); authenticating=false;
        final byte[] digits=current.confirm(result==RESULT_OK,SystemClock.elapsedRealtime());
        if(digits==null) {
            attempt=null;
            setBusy(false);
            show(current.isExpired()?"Phiên xác nhận đã hết hạn. Không gửi PIN. Bấm Kiểm tra laptop để thử lại.":"Đã hủy. Không gửi PIN.");
            return;
        }
        setBusy(true); show("Đang mở khóa… Chỉ gửi một lần.");
        worker.execute(()->{
            String code;
            try { code=connection.unlockWithPin(digits,current.cancelled).optString("status"); }
            catch(Exception ignored) { code="unknown_result"; }
            finally { Arrays.fill(digits,(byte)0); }
            final String message=message(code);
            runOnUiThread(()->{ if(!destroyed && attempt==current) { current.cancel(); laptopStatus="unavailable"; setBusy(false); show(message); } });
        });
    }
    private void cancelAttempt() { if(attempt!=null) attempt.cancel(); }
    private void removeExpiry() { if(expire!=null) { handler.removeCallbacks(expire); expire=null; } }
    @Override protected void onPause() {
        super.onPause(); if(pin!=null) pin.getText().clear();
        if(!authenticating) { cancelAttempt(); laptopStatus="unavailable"; setBusy(busy); }
    }
    @Override protected void onSaveInstanceState(Bundle state) { /* Never save this credential screen. */ }
    @Override protected void onDestroy() {
        destroyed=true; cancelAttempt(); removeExpiry(); worker.shutdown(); super.onDestroy();
    }
    static String message(String code) {
        switch(code) {
            case "locked": return "Laptop đang khóa. Bạn có thể nhập PIN rồi bấm Mở khóa ngay.";
            case "unlocked": return "Windows đang mở khóa.";
            case "not_locked": return "Windows không ở trạng thái khóa. Không gửi phím.";
            case "not_paired": return "Vào mục Kết nối để ghép QR với laptop trước.";
            case "service_unavailable": case "helper_unavailable": return "Alex Unlock trên laptop chưa sẵn sàng. Bản mở khóa này đang thử nghiệm; chưa thể mở khóa ở bước này.";
            case "pin_field_unavailable": return "Chưa xác định được ô PIN Windows. Không gửi PIN; chọn đăng nhập bằng PIN trên laptop rồi thử lại.";
            case "rate_limited": return "Đã đạt giới hạn 3 lần trong một phút. Chờ một phút trước khi thử lại.";
            case "busy": return "Đang xử lý lần trước. Chờ kết quả trước khi thử tiếp.";
            case "expired_challenge": return "Yêu cầu đã hết hạn hoặc đã được dùng. Không gửi lại PIN.";
            case "cancelled": return "Đã hủy trước khi gửi PIN.";
            case "invalid_pin": return "PIN phải gồm 4–20 chữ số.";
            case "offline": return "Chưa kết nối được laptop. Kiểm tra Alex trên PC và mạng Wi-Fi hoặc Tailscale.";
            case "certificate_error": return "Không xác minh được chứng chỉ của laptop. Alex đã dừng trước khi gửi PIN. Kiểm tra chứng chỉ ghép nối hoặc phần mềm kiểm tra HTTPS trên đường kết nối.";
            case "redirect_blocked": return "Địa chỉ laptop yêu cầu chuyển hướng. Alex đã chặn chuyển hướng và không gửi lại PIN. Kiểm tra kết nối trước khi thử tiếp.";
            case "invalid_endpoint": return "Địa chỉ laptop đã lưu không hợp lệ. Vào Kết nối để kiểm tra lại.";
            default: return "Chưa xác định được kết quả. Alex không tự gửi lại PIN. Bấm Kiểm tra laptop trước khi thử tiếp.";
        }
    }
}
