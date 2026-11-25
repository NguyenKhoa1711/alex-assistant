# Alex Assistant & Tra bài

Bản mã nguồn riêng tư cập nhật ngày 25/11/2026, theo yêu cầu của chủ dự án. Theo lựa chọn cuối cùng, chỉ gồm Alex trên laptop và chức năng Tra bài; không gồm robot ESP32, kiểm soát máy trạm hay nhóm điện thoại.

## Có trong repo

- Pet trên desktop và ứng dụng Alex: trò chuyện chữ/giọng nói, STT đa ngôn ngữ, Gemma cục bộ, TTS và nhớ tạm theo phiên.
- Router và agent thao tác web, ứng dụng và tệp trên chính máy chạy Alex; thao tác cửa sổ, nhạc, âm lượng và độ sáng.
- Trạm chỉ huy, avatar, Vũ trụ Alex, camera cử chỉ bật theo lựa chọn và hiệu ứng bóc tách hành tinh.
- Tra cứu web và hỗ trợ đọc/giải bài từ ảnh; một số chức năng cần dịch vụ ngoài và khóa API của người cài. Không bảo đảm mọi đáp án đều đúng.
- `mcp/`: mã công cụ cục bộ. `desktop/tests/`: kiểm thử.

## Không đưa lên trong bản này

- Robot ESP32 và các dự án phần cứng.

- PC Control, agent trên máy trạm thứ hai và dữ liệu kiểm soát máy tính.
- Toàn bộ Android/APK, ghép QR/TLS/Bluetooth, kết nối điện thoại và dịch vụ mở khóa từ xa.
- Khóa API, token, chứng chỉ riêng, khóa ký, cấu hình cá nhân, lịch sử chat, bản thu, ảnh màn hình thật, model GGUF và môi trường đã cài.

Đây là bản xuất độc lập; ứng dụng đang cài trên máy chủ dự án vẫn giữ đầy đủ các tính năng đã loại khỏi GitHub. Các import/nút giao diện liên quan đã được gỡ trong bản xuất để tránh phụ thuộc vào tệp không có trong repo.

## Chạy trên Windows

1. Cài Python 3.11 và `uv`. Trong `desktop/`, sao chép `config.example.yaml` thành `config.yaml`.
2. Điều chỉnh đường dẫn model và thiết bị âm thanh theo máy. Xem `desktop/GEMMA-LOCAL.md`; model và bộ chạy phải được cài riêng.
3. Chạy `desktop/setup.bat`, sau đó `desktop/run.bat` hoặc `desktop/desktop_launch.py` trong môi trường phù hợp. Dùng `launch.py --app` để mở cửa sổ Alex.
4. API ngoài là tùy chọn và cần khóa riêng của người dùng; không nhập khóa vào mã nguồn hay commit. Các tính năng quan sát/điều khiển màn hình chỉ dùng trên máy bạn được phép thao tác.

## Kiểm thử và lịch sử

Xem `docs/GITHUB-EXPORT-20261125.md` về phạm vi và kết quả kiểm tra bản xuất. Lịch sử commit cũ của repo được giữ nguyên, nên có thể còn phiên bản Android từ các lần tải lên trước. Bản hiện tại không chứa các nhóm bị loại. Không viết lại lịch sử Git trong đợt này.

Tài nguyên bên thứ ba giữ giấy phép tương ứng; xem `THIRD_PARTY.md` và các tệp LICENSE trong từng thành phần. Repo chưa cấp giấy phép nguồn mở chung cho mã riêng của Alex.
