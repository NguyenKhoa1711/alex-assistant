package vn.alex.phone;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Canvas;
import android.graphics.ImageFormat;
import android.graphics.Paint;
import android.hardware.Camera;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.google.zxing.BinaryBitmap;
import com.google.zxing.LuminanceSource;
import com.google.zxing.NotFoundException;
import com.google.zxing.PlanarYUVLuminanceSource;
import com.google.zxing.Result;
import com.google.zxing.common.HybridBinarizer;
import com.google.zxing.qrcode.QRCodeReader;

import java.util.Arrays;
import java.util.List;

@SuppressWarnings("deprecation")
public final class QrScannerActivity extends Activity
        implements SurfaceHolder.Callback, Camera.PreviewCallback {
    private static final int CAMERA_PERMISSION = 20;
    private SurfaceView preview;
    private TextView message;
    private Camera camera;
    private boolean surfaceReady;
    private boolean decoding;
    private boolean complete;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(0xff143b49);
        getWindow().setNavigationBarColor(Color.BLACK);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setBackgroundColor(0xff143b49);
        TextView back = UiKit.text(this, "←  Trở lại", 15, 0xffb9e6e4, true);
        back.setPadding(UiKit.dp(this, 20), UiKit.dp(this, 14),
                UiKit.dp(this, 20), UiKit.dp(this, 14));
        back.setOnClickListener(v -> finish());
        layout.addView(back);
        TextView title = UiKit.text(this, "Quét mã QR", 24, Color.WHITE, true);
        title.setPadding(UiKit.dp(this, 20), UiKit.dp(this, 4),
                UiKit.dp(this, 20), UiKit.dp(this, 4));
        layout.addView(title);
        message = UiKit.text(this, "Hướng camera vào mã QR đang hiện trên PC", 14,
                0xffc9e2e6, false);
        message.setText("Hướng camera vào mã QR đang hiện trên PC");
        message.setPadding(UiKit.dp(this, 20), UiKit.dp(this, 4),
                UiKit.dp(this, 20), UiKit.dp(this, 18));
        layout.addView(message);
        FrameLayout cameraFrame = new FrameLayout(this);
        layout.addView(cameraFrame, new LinearLayout.LayoutParams(-1, 0, 1));
        preview = new SurfaceView(this);
        cameraFrame.addView(preview, new FrameLayout.LayoutParams(-1, -1));
        cameraFrame.addView(new ScanFrameView(this), new FrameLayout.LayoutParams(-1, -1));
        preview.getHolder().addCallback(this);
        TextView footnote = UiKit.text(this, "Giữ điện thoại ổn định. Mã được lưu sau khi ghép thành công.",
                13, 0xffc9e2e6, false);
        footnote.setGravity(Gravity.CENTER);
        footnote.setPadding(UiKit.dp(this, 20), UiKit.dp(this, 18),
                UiKit.dp(this, 20), UiKit.dp(this, 24));
        layout.addView(footnote);
        setContentView(layout);
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.CAMERA}, CAMERA_PERMISSION);
    }

    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] grants) {
        super.onRequestPermissionsResult(code, permissions, grants);
        if (code == CAMERA_PERMISSION) {
            if (grants.length > 0 && grants[0] == PackageManager.PERMISSION_GRANTED) startCamera();
            else message.setText("Cần quyền Camera để quét QR. Bạn vẫn có thể dán liên kết ghép nối.");
        }
    }

    @Override public void surfaceCreated(SurfaceHolder holder) {
        surfaceReady = true;
        startCamera();
    }

    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) { }

    @Override public void surfaceDestroyed(SurfaceHolder holder) {
        surfaceReady = false;
        stopCamera();
    }

    @Override protected void onResume() {
        super.onResume();
        startCamera();
    }

    @Override protected void onPause() {
        stopCamera();
        super.onPause();
    }

    private void startCamera() {
        if (!surfaceReady || camera != null || complete
                || checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) return;
        try {
            camera = Camera.open();
            Camera.Parameters parameters = camera.getParameters();
            List<Camera.Size> sizes = parameters.getSupportedPreviewSizes();
            Camera.Size best = sizes.get(0);
            for (Camera.Size size : sizes) {
                if (Math.abs(size.width * size.height - 640 * 480)
                        < Math.abs(best.width * best.height - 640 * 480)) best = size;
            }
            parameters.setPreviewSize(best.width, best.height);
            parameters.setPreviewFormat(ImageFormat.NV21);
            if (parameters.getSupportedFocusModes() != null && parameters.getSupportedFocusModes()
                    .contains(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE))
                parameters.setFocusMode(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE);
            camera.setParameters(parameters);
            camera.setDisplayOrientation(90);
            camera.setPreviewDisplay(preview.getHolder());
            camera.startPreview();
            camera.setOneShotPreviewCallback(this);
        } catch (Exception error) {
            message.setText("Không mở được camera: " + error.getMessage());
            stopCamera();
        }
    }

    private void stopCamera() {
        decoding = false;
        if (camera != null) {
            try { camera.setPreviewCallback(null); camera.stopPreview(); camera.release(); }
            catch (Exception ignored) { }
            camera = null;
        }
    }

    @Override public void onPreviewFrame(byte[] frame, Camera source) {
        if (decoding || complete || camera == null) return;
        decoding = true;
        Camera.Size size = source.getParameters().getPreviewSize();
        byte[] copy = Arrays.copyOf(frame, frame.length);
        new Thread(() -> {
            String decoded = null;
            try {
                LuminanceSource luminance = new PlanarYUVLuminanceSource(copy,
                        size.width, size.height, 0, 0, size.width, size.height, false);
                QRCodeReader reader = new QRCodeReader();
                try {
                    Result result = reader.decode(new BinaryBitmap(new HybridBinarizer(luminance)));
                    decoded = result.getText();
                } catch (NotFoundException noCode) {
                    reader.reset();
                    Result result = reader.decode(new BinaryBitmap(
                            new HybridBinarizer(luminance.rotateCounterClockwise())));
                    decoded = result.getText();
                }
            } catch (Exception ignored) { }
            String result = decoded;
            runOnUiThread(() -> {
                decoding = false;
                if (camera == null || complete) return;
                if (result != null && result.startsWith("alexphone://pair?")) {
                    complete = true;
                    setResult(RESULT_OK, new Intent().setData(Uri.parse(result)));
                    finish();
                } else {
                    camera.setOneShotPreviewCallback(this);
                }
            });
        }, "alex-qr-decode").start();
    }

    private static final class ScanFrameView extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        ScanFrameView(android.content.Context context) { super(context); }
        @Override protected void onDraw(Canvas canvas) {
            float side = Math.min(getWidth() * .78f, getHeight() * .58f);
            float left = (getWidth() - side) / 2f;
            float top = (getHeight() - side) / 2f;
            float right = left + side;
            float bottom = top + side;
            paint.setColor(0x99071824);
            paint.setStyle(Paint.Style.FILL);
            canvas.drawRect(0, 0, getWidth(), top, paint);
            canvas.drawRect(0, bottom, getWidth(), getHeight(), paint);
            canvas.drawRect(0, top, left, bottom, paint);
            canvas.drawRect(right, top, getWidth(), bottom, paint);
            paint.setColor(0xff8de8db);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(UiKit.dp(getContext(), 5));
            float corner = UiKit.dp(getContext(), 30);
            canvas.drawLine(left, top + corner, left, top, paint);
            canvas.drawLine(left, top, left + corner, top, paint);
            canvas.drawLine(right - corner, top, right, top, paint);
            canvas.drawLine(right, top, right, top + corner, paint);
            canvas.drawLine(left, bottom - corner, left, bottom, paint);
            canvas.drawLine(left, bottom, left + corner, bottom, paint);
            canvas.drawLine(right - corner, bottom, right, bottom, paint);
            canvas.drawLine(right, bottom - corner, right, bottom, paint);
            paint.setStyle(Paint.Style.FILL);
        }
    }
}
