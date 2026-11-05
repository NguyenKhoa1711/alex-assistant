# Alex — ưu tiên tạm thời khi khóa máy

Cập nhật 26/10/2026, đã triển khai trên laptop. Không cần cài lại APK 1.8.1.

## Cách hoạt động

- Khi Windows đang mở khóa, yêu cầu giữ màn hình sáng của Antigravity có hiệu lực bình thường.
- Cắm sạc, mở nắp, nói “Tắt máy”: Alex khóa Windows một lần, ngừng mic và bỏ lệnh nguồn lặp. Bộ ưu tiên chỉ tạm bỏ qua yêu cầu DISPLAY của `Antigravity.exe`, đồng thời đặt thời gian tắt màn hình khóa AC thành 2 giây.
- Khi Windows mở khóa, bộ ưu tiên khôi phục nguyên trạng quy tắc Antigravity và thời gian tắt màn hình khóa trước đó (máy này: 30 giây). Antigravity vẫn chạy suốt quá trình.
- Thoát Alex hoặc hủy yêu cầu cũng khôi phục. Nếu helper bị dừng đột ngột, nhật ký khôi phục được xử lý khi đăng nhập/mở khóa hoặc chạy lại tác vụ. Tác vụ không lặp lại yêu cầu cũ.
- Chỉ xử lý Antigravity. Không thay quy tắc của Chrome hay ứng dụng khác đang giữ màn hình sáng.

Laptop vẫn hoạt động nền trên AC để nhận lệnh mạng qua Tailscale; đây không phải Sleep thật hay bật máy đã Shutdown. “Tắt nguồn” vẫn Shutdown. Sleep trực tiếp trong Windows, gập nắp hoặc rút sạc vẫn có thể khiến kết nối từ xa ngừng hoạt động.

## Thành phần

`pet/display_priority.py` gửi vé ngắn hạn đến tác vụ `Alex Display Priority`. Helper được bảo vệ tại `D:\AlexPowerPriority-System`, chạy quyền quản trị của tài khoản đang dùng, không nâng quyền toàn bộ pet. Chỉ thư mục `requests` cho phép tài khoản này ghi yêu cầu; chương trình, cấu hình, trạng thái và nhật ký khôi phục thuộc quyền quản trị. Helper không có mạng, PIN, lệnh shell tùy ý hoặc đường dẫn chương trình do yêu cầu cung cấp.

Tác vụ chờ xác nhận Windows thật sự khóa mới áp dụng thay đổi. Nếu helper không sẵn sàng, Alex không tự chuyển sang Sleep. Helper kết thúc sau khôi phục; khi Windows đang mở không có vòng lặp nền của helper. Khi khóa, nó kiểm tra trạng thái mỗi 250 ms.

Alex vẫn giữ SYSTEM + EXECUTION trên AC, không giữ DISPLAY, nhả khi rút sạc/thoát và tạo lại sau resume. AC idle sleep Never, DC 180 giây; display idle thường 180 giây; lock-display bình thường AC/DC 30 giây. Chỉ lock-display AC được đổi tạm trong yêu cầu của Alex.

Không thay đổi dịch vụ nhập PIN AlexUnlock, TLS, ghép nối, Tailscale hoặc firewall. SHA-256 AlexUnlock vẫn là `53D7BBCDF4B7D09D7C921A2770F7C557AA8DD6E63C1DC46340BFCF5D50AF73BF`.

## Kiểm tra ngày 26/10/2026

- 37 bài kiểm tra Python đạt, cùng self-test C#: câu lệnh nguồn, khóa một lần, chặn lặp, AC/DC, lỗi API, hủy yêu cầu và không chấp nhận trạng thái của vé cũ.
- Thử tác vụ khi Windows chưa khóa: nhận yêu cầu trong 0,359 giây, không áp dụng override; hủy xong không còn nhật ký thay đổi đang hoạt động.
- Lượt giọng nói thật: `POWER requested=sleep executing=remote_wait` lúc 00:04:05; `DISPLAY_PRIORITY active` lúc 00:04:07.
- Người dùng xác nhận mở khóa bằng Alex trên OPPO. Helper ghi `restored` lúc 00:04:46.
- Đọc lại Windows lúc 00:06:06: không còn request override nào, Antigravity vẫn có yêu cầu DISPLAY, lock-display AC/DC đều 30 giây, không còn `active.json`; Task Scheduler trả kết quả 0.
- Đã so mã bản chạy và bản nguồn. Bản sao trước cập nhật ở `before-priority-20261026-000201`; danh sách tệp và SHA-256 nằm trong `display-priority-deployment.json`.

Chưa đo lại thời gian tắt màn hình hoặc kết nối qua mạng khác trong lượt này; không dùng kết quả mở khóa ngắn để khẳng định khả năng chờ nhiều giờ. Bài đo TLS/màn hình ngày 25/10 thuộc bản trước và được giữ riêng để tham khảo.

## Khôi phục

Thoát Alex ở khay hệ thống, chạy `Restore-NormalSleep.ps1` bằng quyền quản trị, rồi mở Alex lại. Script gỡ tác vụ ưu tiên sau khi khôi phục thay đổi đang áp dụng, tắt `remote_wait_on_ac` và phục hồi thời gian ngủ/màn hình từ bản sao lưu. Tệp helper được giữ để phục hồi, không xóa dữ liệu người dùng.

`Uninstall-DisplayPriority.ps1` chỉ gỡ tác vụ ưu tiên: phải thoát Alex và tắt chế độ chờ từ xa hoặc hoàn nguyên mã gọi helper trước khi dùng riêng script này. Giữ các bản sao `before-*`, `deployment-result.json` và `fast-lock-before.json`.

Các script cài đặt và bản sao cấu hình được chuẩn bị riêng cho laptop này; không chạy lại trên một máy khác mà chưa kiểm tra SID, cấu hình và đường dẫn. `Install-DisplayPriority.ps1` yêu cầu người quản trị truyền `-ExpectedUserSid` của tài khoản đích; script vẫn từ chối nếu SID không khớp. Các bản sao cấu hình máy và tệp helper đã biên dịch được giữ ngoài Git.
