# Bản xuất GitHub: Alex và Tra bài — 25/11/2026

## Phạm vi cuối cùng của người dùng

Chỉ gửi Alex trên laptop và Tra bài. Không gửi robot ESP32, nhóm Kiểm soát máy tính (máy trạm thứ hai), Android/APK, kết nối điện thoại, ghép QR/Bluetooth/TLS hay mở khóa từ xa.

Bản xuất được tạo riêng, không sửa mã nguồn hay chương trình đang chạy trên laptop. Các chức năng đã loại vẫn hoạt động ở bản cài của chủ dự án. Bản GitHub được gỡ import/menu/dashboard của các phần bị loại để không phụ thuộc vào các module vắng mặt. Kiểu dữ liệu công việc âm thanh nội bộ và phép đọc trạng thái phiên Windows được tách thành `audio_jobs.py` và `session_state.py`; chúng không mở máy chủ hay gửi thông tin đăng nhập.

Vẫn giữ router/agent thao tác web, ứng dụng và tệp trên chính máy chạy Alex; đây là chức năng của trợ lý, khác với module quản lý máy trạm đã loại. `windows-display-priority` là nguồn helper điều chỉnh ưu tiên màn hình cục bộ, không phải dịch vụ nhận PIN từ điện thoại.

## Dữ liệu không phân phối

Không kèm cấu hình người dùng, Alex-data, khóa API/token, khóa ký/chứng chỉ riêng, dữ liệu ghép nối, log, lịch sử hội thoại, bản thu hoặc ảnh màn hình thật. Model GGUF/STT/TTS lớn, môi trường Python đã cài, SDK, cache và bộ cài được cài riêng. Giữ tài nguyên giao diện cần cho pet và camera cử chỉ cùng thông báo bên thứ ba.

## Kiểm tra bản xuất

- **190 kiểm thử tự động đạt**: lõi VAD/STT với model giả, router app, giao diện/offscreen, bộ điều khiển, yêu cầu gõ, đóng tab, giữ tính cách và lịch sử, TTS, Tra bài, tác vụ đa bước, xác minh tìm kiếm, quyền riêng tư tin nhắn và phạm vi bản xuất.
- Điều chỉnh test double cũ sang giao diện `speak_sequence`; dùng fixture schema công cụ không chứa phiên quan sát thật; kiểm tra tính cách theo nội dung đang cấu hình thay vì đòi một từ của prompt cũ. Không sửa tính cách thật để làm test qua.
- Thử riêng dashboard có Trò chuyện và không còn navigation Kiểm soát máy tính/điện thoại. Xác nhận module Tra bài và phím tắt vẫn có.
- Rà cú pháp Python và mẫu khóa riêng/token/API key trong các tệp văn bản được xuất; không có phát hiện trong lần rà này. Đây là kiểm tra theo mẫu, không phải bảo đảm tuyệt đối phát hiện mọi bí mật có thể tồn tại.
- Không chạy lại model/GPU, thử mic thật, gọi dịch vụ giải bài tính phí, hay thao tác máy trạm thật trong đợt tải mã này. Test không bảo đảm đáp án Tra bài chính xác cho mọi môn/bài.

Các kiểm thử được chạy bằng Python 3.11 và các dependency của Alex đã cài trên laptop. Máy khác cần tạo môi trường và cấu hình riêng theo README.

## Lịch sử Git

Cập nhật nối tiếp nhánh `main` của repo riêng tư `NguyenKhoa1711/alex-assistant`; không force-push và không viết lại commit cũ. Cây mã của bản này không có các phần bị loại. Commit trước đây có thể vẫn chứa bản Android cũ đã được tải lên từ trước.
