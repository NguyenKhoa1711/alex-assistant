# Alex mới 1.8.1 — bản sửa mic 23

Theo yêu cầu quay lại cách cũ, bản này khôi phục giao diện và luồng trò chuyện của Alex 1.8.1 trước đợt thiết kế lại. Thay thao tác chạm hai lần bằng **giữ để nói, thả để gửi**.

## Cài cập nhật

Mở `Alex-moi-v1.8.1-fix-mic-23.apk` trên điện thoại và chọn **Cập nhật** cho **Alex mới**. Cùng package `vn.alex.phone.refresh`, cùng khóa ký với bản 22; versionCode tăng lên 23. Không gỡ app, dữ liệu ghép nối và quyền đã cấp được giữ khi cập nhật. App Alex cũ (`vn.alex.phone`) vẫn riêng biệt.

Nếu chưa có quyền mic: chọn Cho phép khi Android hỏi, rồi giữ nút lần nữa. Khi nút hiện **Thả để gửi** và Alex báo **Đang nghe bạn nói…**, nói câu cần hỏi; nói xong thả tay. Có thể kéo ra ngoài nút để hủy. TalkBack/bàn phím vẫn dùng một lần kích hoạt để bắt đầu và lần nữa để gửi.

Laptop cần chạy Alex, đang thức và mở khóa khi trò chuyện; dùng cùng Wi-Fi hoặc Tailscale. Bản sửa không thay ghép nối, chứng chỉ, quy tắc Avast, mở khóa hay cảnh báo.

## Phần sửa

- Khôi phục AudioRecord PCM16 mono 16 kHz, đọc blocking 3200 byte như bản cũ. Khởi động mic và kiểm tra trạng thái trước khi báo đang nghe.
- Thả tay gọi stop để kết thúc đọc ngay, gửi đúng một lượt. Không tự gửi lại khi lỗi sau khi tải câu hỏi lên.
- Khôi phục nguyên bản `AlexConnection.sendVoice()` và endpoint `/turn`, cùng cách nhận đầy đủ câu trả lời và phát AudioTrack. Không dùng `/turn-stream` trong bản này.
- Giới hạn mỗi lượt 20 giây; rời màn hình hoặc hủy thu thì bỏ bản thu. Không lưu bản thu ra file. Quyền mic thiếu/bị từ chối có hướng dẫn riêng.

## Kiểm tra và giới hạn

- 9 kiểm tra logic giữ/thả/hủy/gửi một lần.
- 11 kiểm tra API thu âm bằng AudioRecord giả: start trước ready, stop giải phóng đọc blocking, giữ PCM khi thả, hủy bỏ PCM, giải phóng mic, lỗi start/read, chạm quá ngắn.
- Biên dịch API 35/min API 28, kiểm tra package/version/activity và chữ ký trùng bản 22.
- Các kiểm tra trên không thay thế mic/loa thật trên OPPO. Chưa có điện thoại ADB kết nối nên chưa xác nhận trò chuyện đầu-cuối trên máy người dùng.
- Laptop đã được sửa riêng: phục hồi 4156 file chương trình Bionic 1.1.7+7 bị thiếu từ bộ cài ký hợp lệ của Element Labs, nối lại đường dẫn tương thích bị mất, khôi phục Qwen3.5-4B Q4_K_M, dùng tên chỉ mục `qwen3.5-4b`. API tự khởi động trên localhost 1234 và không ghi nội dung nhạy cảm.
- Kiểm tra 27/10/2026 qua đúng `LocalChat.stream` của Alex: “Hai cộng ba bằng mấy?” → “Hai cộng ba bằng năm nhé!”, 1,31 giây tổng / 1,14 giây tới token đầu khi model đã nạp. Đây là số đo riêng phần model trên laptop, không phải độ trễ micro/điện thoại.

## Build

`build.ps1` cần `-JdkRoot`, `-BuildTools`, `-AndroidJar`, `-SigningKey`. Dùng lại khóa `Khoa-ky/Alex-moi/alex-refresh.keystore` trong thư mục dự án. Không tạo khóa mới hoặc đưa khóa lên GitHub. Các thay đổi trước khi xuất bản được sao lưu tại `Luu-tru/truoc-apk-micfix23-20261026`; báo cáo tại `Bao-cao/apk-micfix23-20261026`.
