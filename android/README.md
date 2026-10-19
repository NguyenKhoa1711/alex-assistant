# Alex Android

Ứng dụng native Java cho Android 9 trở lên. Bản nguồn hiện tại: 1.7 / versionCode 19.

## Chuẩn bị và build

- Đặt JDK trong `toolchain/jdk/<tên-jdk>/`.
- Đặt Android SDK trong `toolchain/sdk/`, gồm platform `android-35` và build-tools `35.0.0`.
- Cài Python 3 với launcher `py` trên Windows.
- ZXing Core 3.5.4 nằm trong `app/libs/`; giấy phép trong `app/libs/LICENSE-zxing.txt`.
- Chạy `build.ps1` bằng PowerShell. Script dùng một junction tạm có tên ASCII để các công cụ Android xử lý được đường dẫn tiếng Việt.

APK được tạo tại `dist/Alex-Android.apk`. Với bản cập nhật, dùng lại khóa gốc `dist/alex-debug.keystore` từ bản sao lưu riêng; không commit khóa. Không tạo khóa mới nếu muốn cài đè bản đang dùng. Build mới chưa có APK/khóa sẽ tạo khóa phát triển cục bộ theo script.

## Cấu hình khi cài mới

Ghép QR từ PC một lần, cấp microphone/camera khi dùng. Bluetooth HID tùy thuộc thiết bị hỗ trợ; ghép với Windows trước khi thử mở khóa. Chỉ nhập PIN trên điện thoại.

Tên liên hệ mẫu đã được thay bằng “Người thân 1”, “Người thân 2” trong bản nguồn GitHub. Điền đúng người nhận trong thiết lập trước khi dùng cảnh báo; bản đang cài trên máy của chủ dự án giữ nguyên. Số điện thoại/SIM được lưu ở thiết bị, không ở repo. Chỉ kiểm tra cảnh báo bằng chế độ không gửi; gửi thật cần thao tác chủ động của người dùng.
