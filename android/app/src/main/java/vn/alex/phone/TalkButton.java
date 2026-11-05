package vn.alex.phone;

import android.content.Context;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.ViewConfiguration;
import android.widget.Button;

/** Touch starts immediately; release submits once. TalkBack/keyboard use click-toggle. */
final class TalkButton extends Button {
    interface Listener { boolean begin(); void release(); void cancel(); }
    private final VoiceGesture gesture = new VoiceGesture();
    private Listener listener;
    TalkButton(Context context) { super(context); setClickable(true); setFocusable(true); }
    void setListener(Listener value) { listener = value; }
    void resetGesture() {
        gesture.cancel(); setPressed(false);
        if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(false);
    }
    @Override public boolean onTouchEvent(MotionEvent event) {
        if (!isEnabled() || listener == null) return false;
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                if (!gesture.begin(event.getPointerId(0))) return true;
                if (!listener.begin()) { resetGesture(); return true; }
                setPressed(true);
                if(getParent()!=null) getParent().requestDisallowInterceptTouchEvent(true);
                return true;
            case MotionEvent.ACTION_MOVE:
                int index = event.findPointerIndex(gesture.active() ? event.getPointerId(0) : -1);
                int slop = ViewConfiguration.get(getContext()).getScaledTouchSlop();
                if (gesture.active() && (index < 0 || event.getX(index) < -slop ||
                        event.getY(index) < -slop || event.getX(index) > getWidth()+slop ||
                        event.getY(index) > getHeight()+slop)) cancelPress();
                return true;
            case MotionEvent.ACTION_POINTER_DOWN:
            case MotionEvent.ACTION_CANCEL:
                cancelPress(); return true;
            case MotionEvent.ACTION_POINTER_UP:
                if (gesture.owns(event.getPointerId(event.getActionIndex()))) cancelPress();
                return true;
            case MotionEvent.ACTION_UP:
                if (gesture.release(event.getPointerId(event.getActionIndex()))) listener.release();
                resetGesture(); return true;
            default: return true;
        }
    }
    private void cancelPress() {
        if (gesture.cancel() && listener != null) listener.cancel();
        resetGesture();
    }
    @Override public boolean performClick() {
        super.performClick();
        if (!isEnabled() || listener == null) return false;
        // Accessibility ACTION_CLICK has no physical DOWN/UP pair.
        if (gesture.release(0)) listener.release();
        else if (gesture.begin(0) && !listener.begin()) resetGesture();
        return true;
    }
    @Override public boolean onKeyDown(int key, KeyEvent event) {
        if (key == KeyEvent.KEYCODE_ENTER || key == KeyEvent.KEYCODE_DPAD_CENTER || key == KeyEvent.KEYCODE_SPACE)
            return true;
        return super.onKeyDown(key,event);
    }
    @Override public boolean onKeyUp(int key, KeyEvent event) {
        if (key == KeyEvent.KEYCODE_ENTER || key == KeyEvent.KEYCODE_DPAD_CENTER || key == KeyEvent.KEYCODE_SPACE)
            return performClick();
        return super.onKeyUp(key,event);
    }
}
