package vn.alex.phone;

import android.app.AlertDialog;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;
import android.widget.Button;

/** Releasing, leaving the button, or losing the screen cancels the hold. */
final class HoldButton extends Button {
    private final Handler timer = new Handler(Looper.getMainLooper());
    private final Runnable activate;
    private final String title;
    private Runnable releasedEarly = () -> {};
    private long started;
    private boolean holding;
    private boolean fired;
    private final HoldGate gate = new HoldGate();
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (!holding || fired || !isEnabled() || !hasWindowFocus()) return;
            long elapsed = SystemClock.elapsedRealtime() - started;
            if (gate.fire(SystemClock.elapsedRealtime())) {
                fired = true;
                holding = false;
                setText(title);
                activate.run();
            } else {
                setText("Giữ thêm " + ((AlertPlan.HOLD_MS - elapsed + 999) / 1000) + " giây…");
                timer.postDelayed(this, 80);
            }
        }
    };

    HoldButton(Context context, String title, int color, Runnable activate) {
        super(context);
        this.title = title;
        this.activate = activate;
        setText(title);
        setSoundEffectsEnabled(false);
        setHapticFeedbackEnabled(false);
        setTextSize(16);
        setTypeface(android.graphics.Typeface.create("sans-serif-medium", android.graphics.Typeface.NORMAL));
        setPadding(UiKit.dp(context,14),UiKit.dp(context,12),UiKit.dp(context,14),UiKit.dp(context,12));
        setAllCaps(false);
        setTextColor(0xffffffff);
        setBackground(UiKit.shape(color, 16, context));
        setMinimumHeight(UiKit.dp(context, 64));
        setContentDescription(title + ". Giữ 3 giây để kích hoạt, thả tay để hủy.");
        setOnClickListener(v -> new AlertDialog.Builder(context)
                .setTitle(title).setMessage("Kích hoạt cấp này ngay? Đây là cách thay cho nhấn giữ khi dùng trình đọc màn hình.")
                .setNegativeButton("Hủy", null)
                .setPositiveButton("Kích hoạt", (d, w) -> { if (isEnabled()) activate.run(); }).show());
    }

    void onReleasedEarly(Runnable action) { releasedEarly = action; }

    void cancelHold() {
        gate.cancel();
        holding = false;
        timer.removeCallbacks(tick);
        setPressed(false);
        setText(title);
        if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(false);
    }

    @Override public boolean onTouchEvent(MotionEvent event) {
        if (!isEnabled()) return false;
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                fired = false;
                holding = true;
                started = SystemClock.elapsedRealtime();
                gate.down(started);
                setPressed(true);
                getParent().requestDisallowInterceptTouchEvent(true);
                timer.post(tick);
                return true;
            case MotionEvent.ACTION_MOVE:
                if (event.getX() < 0 || event.getY() < 0 || event.getX() >= getWidth()
                        || event.getY() >= getHeight()) cancelHold();
                return true;
            case MotionEvent.ACTION_UP:
                boolean activateOnRelease = holding && !fired && gate.fire(SystemClock.elapsedRealtime());
                boolean early = holding && !fired && !activateOnRelease;
                cancelHold();
                if (activateOnRelease) { fired = true; activate.run(); }
                else if (early) releasedEarly.run();
                return true;
            case MotionEvent.ACTION_CANCEL:
            case MotionEvent.ACTION_POINTER_DOWN:
                cancelHold();
                return true;
            default: return true;
        }
    }

    @Override public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        if (!focused) cancelHold();
    }
    @Override protected void onDetachedFromWindow() { cancelHold(); super.onDetachedFromWindow(); }
}
