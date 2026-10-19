# Alex — robot tròn xanh ngọc, nhìn theo chuột

Pet dùng [robot-heads của Fayaz Ahmed](https://github.com/fayazara/robot-heads), MIT; mã nguồn cố định ở `58ebf6439a8125a769f63b22ffd35bc18834b1b5` (0.3.0). Hình tròn, màu vỏ `#259791`, kích thước 110.

## Sử dụng

- Rê chuột trên màn hình: mắt nhìn và đầu xoay theo, có chuyển động đàn hồi như demo.
- Chuột phải pet → **Mắt và đầu nhìn theo chuột** để bật/tắt. Lựa chọn được lưu trong config.yaml.
- Tắt mic vẫn nhìn theo chuột. Khi tắt cả theo chuột lẫn mic, robot có biểu cảm ngủ.
- Ctrl+Space mở/ẩn và bật/tắt mic; bấm pet ngắt lời hoặc đổi trạng thái mic; kéo để di chuyển.
- Chuột phải → **Hình dáng pet → Alex hoạt hình (hình cũ)** để trở lại mascot.
- `main.py --show-muted` mở để xem, mic vẫn tắt cho đến khi người dùng bật.

```yaml
pet:
  shape: robot-heads
  robot_renderer: live
  follow_cursor: true
  size: 110
  fps: 30
```

## Chuyển động và tài nguyên

QtWebEngine dựng canvas trực tiếp từ geometry, lighting, simulation và renderer gốc. Mắt/đầu phản ứng theo con trỏ trong các trạng thái hỗ trợ của bộ gốc (idle, listening, speaking, happy); thinking/error/working có động tác riêng. Miệng nói theo trạng thái, chưa khớp từng âm tiết.

Qt lấy vị trí chuột toàn màn hình, ánh xạ vào hệ tọa độ của pet và truyền số tọa độ qua JavaScript. Mỗi lần chỉ có một khung đang xử lý, không tích hàng đợi. Khi mic tắt hoặc idle và chuột đứng yên trên 1,2 giây, giảm còn tối đa 8 khung/giây; rê chuột lại sẽ tăng theo `pet.fps`. Ẩn pet hoặc đổi sang mascot dừng vẽ canvas.

Để phù hợp hình 110px, bản build giảm độ chia lưới bevel từ 10 xuống 4, cung viền từ 14 xuống 8 và phần tròn từ 36 xuống 16. Nguồn upstream trong `source/` giữ nguyên; bước chuyển đổi có kiểm tra chuỗi nguồn trước khi áp dụng.

Đo trên laptop ngày 14/10/2026 bằng bộ điều khiển giả, không mic/model: khoảng 11,2ms cho phần vẽ canvas; khi đứng yên khoảng 7,15 khung/giây. Lấy mẫu CPU 3 giây của cửa sổ thử và tiến trình vẽ: khoảng 3% tổng CPU trên 12 luồng, working set cộng gộp khoảng 427MiB (có thể tính trùng bộ nhớ dùng chung), private memory khoảng 263MiB. Đây không phải số đo toàn bộ Alex hoặc độ trễ STT/LLM/TTS. Bộ vẽ trực tiếp tốn RAM hơn sprite vì có QtWebEngine.

## Cách ly trang vẽ

Trang nằm trong bộ nhớ, dùng profile riêng không lưu cookie/cache, chặn request tệp/mạng bằng URL interceptor và Content Security Policy. Trang không có quyền mic, camera, clipboard hoặc tải tệp; âm thanh trang luôn tắt. Không dùng React, CDN, máy chủ HTTP hay kết nối Internet để vẽ. Cơ chế này chỉ áp dụng trang vẽ pet; các chức năng mạng đã cấu hình của Alex không thay đổi.

Nếu live renderer không tải hoặc bị dừng, tự dùng bộ PNG đóng gói trước. Có thể chọn `pet.robot_renderer: sprites` rồi khởi động lại để dùng bản nhẹ hơn nhưng không nhìn theo chuột. Bộ PNG giữ 9 trạng thái × 160 khung, cache tối đa 20 khung; nếu asset hỏng, quay về hình QPainter đơn giản.

## Dựng lại và kiểm tra

- `assets/robot-heads/LICENSE`: giấy phép MIT, giữ tên tác giả.
- `assets/robot-heads/source/src/`: nguồn upstream.
- `tools/build_robot_live.cjs` và `tools/robot_live_entry.js`: Node 24 dựng `assets/robot-heads/live.html` độc lập; không cần npm install hoặc mạng.
- Chạy từ thư mục dự án: `node tools/build_robot_live.cjs`.
- `tests/test_robot_live.py`: cửa sổ thật với engine giả, kiểm tra bốn hướng, mic vẫn paused, state signal, click/drag, bật/tắt theo chuột, ẩn/dừng vẽ, đổi hình cũ và CSP chặn request mạng. Đã đạt trên Windows; không thu âm, gửi chat hoặc thao tác máy tính trong test.
- Bài kiểm tra tạo `cursor-preview.png`, `live-test-report.json`; kết quả lần triển khai lưu trong `verification/robot-follow/`.

Các bài kiểm tra sprite trước đó cũng đã đạt: toàn bộ 1.440 PNG, alpha trong suốt, cache giới hạn, lưu riêng cấu hình UI và fallback khi thiếu asset.
