package vn.alex.phone;

import android.content.Context;
import android.app.Activity;
import android.content.res.ColorStateList;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.RippleDrawable;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

final class UiKit {
    static final int BACKGROUND = 0xfff4f7f6;
    static final int INK = 0xff173b42;
    static final int MUTED = 0xff536a70;
    static final int PRIMARY = 0xff087b73;
    static final int PRIMARY_DARK = 0xff075e59;
    static final int PALE = 0xffe3f3ed;
    static final int BORDER = 0xffdbe5e1;
    static final int DANGER = 0xffae3343;
    static final int AMBER = 0xff80520a;
    static final int BLUSH = 0xffffeff0;

    private UiKit() { }

    static int dp(Context context, float value) {
        return Math.round(value * context.getResources().getDisplayMetrics().density);
    }

    static GradientDrawable shape(int color, int radiusDp, Context context) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(context, radiusDp));
        return drawable;
    }

    static GradientDrawable outline(int color, int stroke, int radiusDp, Context context) {
        GradientDrawable drawable = shape(color, radiusDp, context);
        drawable.setStroke(dp(context, 1), stroke);
        return drawable;
    }

    static TextView text(Context context, String value, int sizeSp, int color, boolean bold) {
        TextView view = new TextView(context);
        view.setText(value);
        view.setTextSize(sizeSp);
        view.setTextColor(color);
        view.setFontFeatureSettings("kern");
        view.setTypeface(Typeface.create("sans-serif", bold ? Typeface.BOLD : Typeface.NORMAL));
        view.setGravity(Gravity.CENTER_VERTICAL);
        view.setIncludeFontPadding(false);
        view.setLineSpacing(dp(context, 3), 1);
        return view;
    }

    static LinearLayout column(Context context) {
        LinearLayout layout = new LinearLayout(context);
        layout.setOrientation(LinearLayout.VERTICAL);
        return layout;
    }

    static LinearLayout card(Context context) {
        LinearLayout card = column(context);
        int padding = dp(context, 20);
        card.setPadding(padding, padding, padding, padding);
        card.setBackground(shape(Color.WHITE, 24, context));
        card.setElevation(dp(context, 1));
        return card;
    }

    static LinearLayout.LayoutParams space(Context context, int width, int height,
                                            int top, int bottom) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(width, height);
        params.topMargin = dp(context, top);
        params.bottomMargin = dp(context, bottom);
        return params;
    }

    static Button button(Context context, String title, boolean filled, View.OnClickListener click) {
        Button button = new Button(context);
        button.setText(title);
        button.setAllCaps(false);
        button.setTextSize(15);
        button.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        button.setTextColor(filled ? Color.WHITE : PRIMARY_DARK);
        button.setBackground(ripple(context, filled ? PRIMARY : Color.WHITE, !filled));
        button.setMinHeight(dp(context, 54));
        button.setMinimumHeight(dp(context, 54));
        button.setPadding(dp(context, 14), dp(context, 10), dp(context, 14), dp(context, 10));
        button.setOnClickListener(click);
        button.setContentDescription(title);
        return button;
    }

    static Drawable ripple(Context context, int color, boolean border) {
        return new RippleDrawable(ColorStateList.valueOf(0x22087b73),
                border ? outline(color, BORDER, 18, context) : shape(color, 18, context), null);
    }

    static void field(android.widget.EditText field, String hint) {
        Context c = field.getContext();
        field.setHint(hint); field.setTextSize(16); field.setTextColor(INK);
        field.setHintTextColor(MUTED);
        field.setTypeface(Typeface.create("sans-serif", Typeface.NORMAL));
        field.setBackground(outline(BACKGROUND, BORDER, 16, c));
        field.setPadding(dp(c,16),dp(c,14),dp(c,16),dp(c,14));
        field.setMinimumHeight(dp(c,56));
    }

    static void window(Activity activity, LinearLayout root) {
        activity.getWindow().setStatusBarColor(BACKGROUND);
        activity.getWindow().setNavigationBarColor(Color.WHITE);
        activity.getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        activity.getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            activity.getWindow().setDecorFitsSystemWindows(false);
            root.setOnApplyWindowInsetsListener((view, insets) -> {
                android.graphics.Insets bars = insets.getInsets(android.view.WindowInsets.Type.systemBars());
                android.graphics.Insets ime = insets.getInsets(android.view.WindowInsets.Type.ime());
                view.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, ime.bottom));
                return insets;
            });
        }
    }

    static Drawable icon(Context context, String kind, int color, int size) {
        Drawable drawable = new LineIcon(kind, color);
        drawable.setBounds(0, 0, dp(context, size), dp(context, size));
        return drawable;
    }

    private static final class LineIcon extends Drawable {
        final String kind;
        final Paint pen = new Paint(Paint.ANTI_ALIAS_FLAG);
        LineIcon(String kind, int color) { this.kind=kind; pen.setColor(color); }
        @Override public void draw(Canvas canvas) {
            canvas.save(); canvas.translate(getBounds().left,getBounds().top);
            canvas.scale(getBounds().width()/24f,getBounds().height()/24f);
            pen.setStyle(Paint.Style.STROKE); pen.setStrokeWidth(1.8f);
            pen.setStrokeCap(Paint.Cap.ROUND); pen.setStrokeJoin(Paint.Join.ROUND);
            switch(kind) {
                case "chat":
                    canvas.drawRoundRect(3,3,21,18,5,5,pen);
                    canvas.drawLine(7,18,6,22,pen); canvas.drawLine(6,22,12,18,pen);
                    canvas.drawLine(7,9,17,9,pen); canvas.drawLine(7,13,13,13,pen); break;
                case "lock":
                    canvas.drawRoundRect(5,10,19,21,3,3,pen);
                    canvas.drawArc(8,2,16,16,180,180,false,pen);
                    canvas.drawLine(12,14,12,17,pen); break;
                case "link":
                    canvas.drawRoundRect(3,3,21,17,2,2,pen);
                    canvas.drawLine(12,17,12,21,pen); canvas.drawLine(8,21,16,21,pen);
                    canvas.drawLine(8,10,11,13,pen); canvas.drawLine(11,13,16,7,pen); break;
                case "shield":
                    Path shield = new Path(); shield.moveTo(12,2); shield.lineTo(21,6);
                    shield.lineTo(20,13); shield.quadTo(18,19,12,22);
                    shield.quadTo(6,19,4,13); shield.lineTo(3,6); shield.close(); canvas.drawPath(shield,pen);
                    canvas.drawLine(12,7,12,13,pen); canvas.drawPoint(12,17,pen); break;
                case "mic":
                    canvas.drawRoundRect(9,2,15,15,3,3,pen);
                    canvas.drawArc(5,5,19,19,0,180,false,pen);
                    canvas.drawLine(5,9,5,12,pen); canvas.drawLine(19,9,19,12,pen);
                    canvas.drawLine(12,19,12,22,pen); break;
                case "qr":
                    canvas.drawRect(3,3,9,9,pen); canvas.drawRect(15,3,21,9,pen);
                    canvas.drawRect(3,15,9,21,pen); canvas.drawLine(15,15,21,15,pen);
                    canvas.drawLine(15,15,15,21,pen); canvas.drawPoint(21,21,pen); break;
                case "back":
                    canvas.drawLine(15,5,8,12,pen); canvas.drawLine(8,12,15,19,pen); break;
                case "check":
                    canvas.drawLine(5,12,10,17,pen); canvas.drawLine(10,17,20,6,pen); break;
                default: canvas.drawCircle(12,12,8,pen); canvas.drawPoint(12,12,pen);
            }
            canvas.restore();
        }
        @Override public void setAlpha(int alpha) { pen.setAlpha(alpha); invalidateSelf(); }
        @Override public void setColorFilter(android.graphics.ColorFilter filter) { pen.setColorFilter(filter); }
        @Override public int getOpacity() { return android.graphics.PixelFormat.TRANSLUCENT; }
    }
}
