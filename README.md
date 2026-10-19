# Alex Assistant

Mã nguồn riêng tư của Alex: pet Windows, ứng dụng Android và lớp công cụ kết nối Bionic.
Ảnh chụp mã nguồn ngày 19/10/2026; Android hiện là 1.7 (versionCode 19).

## Thành phần

- `desktop/`: pet, thu âm/VAD, STT, giọng nói, điều hướng lệnh cục bộ, kết nối Bionic và điện thoại, kiểm thử.
- `android/`: chat giọng nói, ghép PC qua QR/TLS, bàn phím Bluetooth HID và cảnh báo theo cấp.
- `mcp/`: máy chủ giọng Việt tùy chọn và phiên bản phụ thuộc Windows MCP.
- `docs/Alex-global-compact.md`: chỉ dẫn Alex trong Bionic.

Bionic là ứng dụng cài riêng, không được đóng gói trong repo. Model AI, Python/JDK/SDK và môi trường ảo cũng được cài riêng.

## Chạy trên Windows

1. Dùng Python 3.11, `uv`, Bionic và model đã thiết lập trên máy. Bionic bridge dùng cổng loopback 9223; dịch vụ model dùng 1234.
2. Chép `desktop/config.example.yaml` thành `desktop/config.yaml`; chọn CPU/CUDA và microphone phù hợp. Điền các thư mục cho phép tìm, đường dẫn Windows MCP và các project Bionic nếu dùng. Mẫu cấu hình không chứa thư mục cá nhân hoặc ID phiên chat.
3. Chạy `desktop/setup.bat` để cài các phụ thuộc và tải model STT đã ghim phiên bản. Cài giọng nói tương ứng; model Piper nếu dùng phải được đặt tại đường dẫn cấu hình. Việc tải model chỉ diễn ra trong bước thiết lập chủ động.
4. Chạy `desktop/run.bat`. Ctrl+Space bật/ẩn pet; cấu hình mặc định không lưu bản thu hoặc nội dung câu nói.

Repo là bản nguồn để phát triển/khôi phục. Bản Alex đang dùng vẫn chạy ở `outputs/Bionic-pet` trong thư mục cài đặt trên ổ D; clone repo không tự thay thế bản đang chạy hoặc dữ liệu của bạn.

## Build Android

Xem [hướng dẫn Android](android/README.md). Khóa ký bản đang cài phải được sao lưu riêng và dùng lại để cập nhật tại chỗ.

## Hành vi quan trọng

- “Đóng tab” đóng một tab trình duyệt và giữ cửa sổ ở tab cuối. Lệnh đóng ứng dụng/cửa sổ mới đóng cả cửa sổ.
- “Tắt máy” là Sleep; “tắt nguồn” là Shutdown. Luồng này thực thi cục bộ theo cấu hình, không dùng model để lặp thao tác.
- Pet có thể dùng Bionic ở nền. Mở Bionic bằng menu khi cần xem chat.
- Ghép điện thoại được lưu cục bộ. Giọng nói qua Wi-Fi cần PC hoạt động và tường lửa cho phép kết nối đã giới hạn; mở khóa dùng Bluetooth HID và xác nhận trên điện thoại, không lưu PIN Windows.
- Cảnh báo Zalo phụ thuộc quyền trợ năng và giao diện Zalo; không gửi thử tới người thật khi chạy kiểm thử.

## Quyền riêng tư và sao lưu

Không commit `config.yaml`, khóa ký APK, chứng chỉ/khóa riêng, thông tin đăng nhập, dữ liệu ghép nối, số điện thoại, lịch sử chat, bản thu, log hay profile trình duyệt. Những dữ liệu này vẫn nằm trên máy và cần bản sao lưu riêng nếu muốn khôi phục trọn vẹn.

Xem [kiểm thử](docs/TESTING.md) và [thành phần bên thứ ba](THIRD_PARTY.md).
