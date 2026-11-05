package vn.alex.phone;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.widget.LinearLayout;

final class RemoteAccessPanel {
    static LinearLayout create(Activity activity) {
        LinearLayout card=UiKit.card(activity);
        card.addView(UiKit.text(activity,"Mở khóa ngay trong Alex",20,UiKit.INK,true));
        card.addView(UiKit.text(activity,"Nhập PIN Windows Hello và xác nhận trên OPPO. Không cần Bluetooth, không chuyển sang RustDesk và không lưu PIN.",14,UiKit.MUTED,false),UiKit.space(activity,-1,-2,10,18));
        card.addView(UiKit.button(activity,"Nhập PIN · Mở khóa laptop",true,v->activity.startActivity(new Intent(activity,DirectUnlockActivity.class))));
        card.addView(UiKit.text(activity,"Cần thiết lập Alex Unlock trên laptop một lần. Dùng khác Wi-Fi cần mạng riêng Tailscale trên hai máy.",13,UiKit.MUTED,false),UiKit.space(activity,-1,-2,14,14));
        card.addView(UiKit.button(activity,"Hướng dẫn kết nối",false,v->
            new AlertDialog.Builder(activity).setTitle("Thiết lập một lần")
                .setMessage("1. Cài Alex Unlock đi kèm bản cập nhật trên laptop.\n\n"
                    +"2. Dùng qua Internet: cài Tailscale trên laptop và OPPO, đăng nhập cùng tài khoản riêng của bạn và bật kết nối mạng riêng.\n\n"
                    +"3. Chạy thiết lập mạng riêng Alex trên laptop, rồi quét QR trong mục Kết nối của Alex.\n\n"
                    +"4. Những lần sau: vào Mở khóa trong Alex, nhập PIN và xác nhận trên OPPO.\n\n"
                    +"Laptop phải đang thức, đã đăng nhập Windows ít nhất một lần và Alex đang chạy. Không chia sẻ mã QR ghép nối.")
                .setPositiveButton("Đã hiểu",null).show()));
        return card;
    }
}
