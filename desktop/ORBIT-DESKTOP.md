# Alex Desktop — Trạm chỉ huy và Vũ trụ Alex

Ngày cập nhật: 29/10/2026. Hai mục nằm ở thanh bên của **Alex - Trò chuyện**.

## Trạm chỉ huy

Thay nút “Các cách nói đã học” trong cửa sổ ứng dụng bằng một trang điều khiển Alex.
Trang này dùng cùng bộ xử lý, mic và giọng nói của pet: bật/tắt mic, ngắt yêu cầu, quay
về trò chuyện, mở HỌC TẬP / YouTube và đọc phản hồi gần nhất. CPU và RAM là số đo
toàn laptop, không phải số liệu giả hay mức sử dụng riêng của model.
Các cách nói đã học không bị xóa; vẫn xem được từ menu chuột phải pet.

Khuôn mặt hiện tại dùng bộ dựng hologram FatihMakes. Nguồn, giấy phép và giới hạn
animation được ghi riêng trong `COMMAND-CENTER-HOLOGRAM.md`.

## Vũ trụ Alex

Giao diện nền tối, quỹ đạo phát sáng và tám hành tinh, lấy cảm hứng tương tác từ:
https://www.youtube.com/shorts/_K9KnTC-SQc

- Kéo chuột trái: xoay góc nhìn. Cuộn chuột: thu phóng.
- Chọn hành tinh trong danh sách hoặc bấm vào hành tinh: xem chu kỳ và khoảng cách.
- Tạm dừng / Tiếp tục: dừng hoặc chạy thời gian mô phỏng.
- Thanh tốc độ: 1–100 ngày mô phỏng mỗi giây. Góc nhìn ban đầu: đưa máy quay về mặc định.
- Khi mô hình có focus: phím mũi tên xoay, `+`/`-` thu phóng.

Đây là mô hình minh họa, không phải vị trí các hành tinh theo ngày thực. Quỹ đạo
ellipse dùng chu kỳ và độ lệch tâm; khoảng cách/kích thước được thu gọn/phóng đại
để nhìn rõ. Dữ liệu tham khảo: NASA Planetary Fact Sheet
https://nssdc.gsfc.nasa.gov/planetary/factsheet/

## Cử chỉ tay — mặc định tắt

Trong Vũ trụ Alex, chọn Camera 1 (hoặc 2/3 nếu có) rồi bấm **Bật camera cử chỉ**.
Chỉ hiện khung xương bàn tay; không hiện hay lưu hình camera.

- Một tay: chụm ngón cái + trỏ, giữ và di chuyển để xoay. Thả để dừng xoay.
- Hai tay: đưa hai tay ra xa nhau để phóng to, lại gần để thu nhỏ.
- Mất dấu bàn tay: dừng thay đổi, không nhảy góc khi nhận lại tay.
- Rời trang Vũ trụ, ẩn/thu nhỏ/đóng cửa sổ: camera tắt. Mở lại phải tự bật.
- Cử chỉ chỉ điều khiển mô hình này, không phát phím/chuột Windows, không gửi lệnh tới Alex.

Nếu camera đang được ứng dụng khác dùng hoặc Windows chưa cấp quyền, ứng dụng hiện lỗi
và vẫn điều khiển được bằng chuột. Camera/model chạy trong tiến trình riêng, tối đa
15 lượt/giây, hình xử lý cục bộ trong RAM. Không tải lên mạng, không lưu khung hình.
Hoạt ảnh tối đa 30 fps và dừng khi ẩn. Bộ cử chỉ không được nạp khi chỉ trò chuyện.

## Kỹ thuật và cài đặt lại

Nguồn: `pet/command_center.py`, `pet/space_view.py`, `pet/orbit_math.py`,
`pet/gesture_worker.py`, tích hợp vào `pet/app_window.py`.

Thư viện camera ở `.venv-gestures` riêng cạnh `.venv` của pet, không thay numpy/STT
đang chạy. Dùng MediaPipe 1.1.1; dependency cố định được lưu ở
`requirements-gestures.lock.txt`. Khi cài lại, dùng Python 3.11 tạo venv này rồi pip
install file lock. Model nằm ở `assets/gestures/hand_landmarker.task`.

Tài liệu MediaPipe:
https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/python

Nguồn model công khai của Google:
https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task

SHA256 model: `fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1`.
Đọc model bằng bytes để hỗ trợ tên thư mục tiếng Việt trên Windows.

Kiểm tra: `tools/verify_orbit.py` (Qt offscreen, không mở camera/mic thật),
`tools/preview_orbit.py <đường-dẫn-live-pet>` (ảnh giao diện),
`gesture_worker.py --model <file.task> --probe` (ảnh đen tổng hợp, không mở camera).

Camera/cử chỉ với bàn tay thật chưa được thử. Người dùng bật nút camera để kiểm tra
với điều kiện ánh sáng trên laptop. Không cần chỉnh cài đặt Bionic, PIN hay điện thoại.

## Bản nâng cấp Đài quan sát — 28/10/2026

- Nền sao nhiều lớp, ánh sáng dịu, quỹ đạo phân biệt phía trước/phía sau và vành đai tiểu hành tinh minh họa.
- Tám hành tinh có bề mặt riêng: lục địa/mây Trái Đất, dải mây Sao Mộc, vành đai Sao Thổ…
  Hình do ứng dụng vẽ tại máy, là minh họa nghệ thuật, không phải ảnh hoặc bản đồ bề mặt chính xác.
- Bấm hành tinh trong mô hình, danh sách hoặc Trước/Tiếp để xem cận cảnh, chu kỳ và khoảng cách.
- **Tham quan tự động**: chuyển hành tinh mỗi 9 giây. **Dừng tham quan** để chọn bằng tay.
  Tạm dừng mô phỏng cũng dừng tham quan; rời trang/ẩn cửa sổ dừng cả hai bộ hẹn giờ.
- **Góc nghiêng / Nhìn từ trên** đổi góc quan sát. Quỹ đạo, tên và vệt sáng bật/tắt độc lập.
- Khi cửa sổ nhỏ, thông tin được rút gọn; chọn hành tinh và nút camera vẫn dùng được.
- Camera vẫn chỉ bật khi người dùng bấm nút; tham quan không mở camera hoặc mic.

## Bản nâng cấp bề mặt và chuyển động — 29/10/2026

- Hành tinh có bề mặt dựng theo tọa độ cầu, bóng sáng/tối và viền khí quyển.
  Trái Đất có biển, đất liền, mây và băng; các hành tinh khác có dải mây, hố va chạm
  hoặc vành đai nhiều lớp. Đây vẫn là hình nghệ thuật, không phải bản đồ chính xác.
- Cận cảnh tự xoay nhẹ khi mô phỏng chạy. Tốc độ tự xoay là hiệu ứng minh họa,
  không đại diện chu kỳ tự quay thật. Ảnh lấy theo DPI màn hình để tránh phóng ảnh nhỏ.
- Mặt Trời có quầng sáng dịu; sao nền nhấp nháy chậm, khung chọn hành tinh chuyển động.
  Nét quỹ đạo được lấy mẫu dày hơn. Nút **Nhìn từ trên** chuyển góc nhìn êm;
  kéo chuột hoặc cử chỉ tay sẽ tiếp quản góc nhìn ngay.
- **Hiệu ứng** bật/tắt tự xoay cận cảnh, quầng sáng động và sao nhấp nháy, giúp giảm tải.
  Nút có trên cửa sổ rộng. **Tạm dừng** dừng cả quỹ đạo và hiệu ứng ở mọi kích thước.
- Đóng/ẩn/thu nhỏ/rời trang dừng bộ hẹn giờ và camera; mở lại không tự bật camera.

Renderer: `pet/orbit_scene.py`, `pet/planet_art.py`, `pet/planet_surface.py`.
Chỉ dùng NumPy và PySide6 đã có. Không tải ảnh/mã từ mạng, không mở mic hoặc camera.
Texture được tạo một lần và cache tối đa 9 bản; Trái Đất 1024×512, còn lại 512×256.
Mô hình dùng 9 sprite 384×384. Cận cảnh chỉ giữ một sprite theo DPI (tối đa 1024×1024),
không giữ atlas hoạt ảnh tích lũy. Hình học cầu cache LRU tối đa 4 kích thước.
Nền sao cache theo size/DPI; quỹ đạo cache theo pose/size. Cận cảnh tối đa 20 khung/giây,
quỹ đạo tối đa khoảng 30 khung/giây; khi ẩn không chạy timer.

32 kiểm tra offscreen đạt: chọn hành tinh, tour, góc nhìn, pause/hide/minimize,
camera opt-in, cache hữu hạn, ảnh DPI cao và vòng quay không nối đường may.
Đo tại máy này: cảnh 1000×500 trung bình 7,34 ms, p95 8,23 ms;
cả trang 1050×780 kèm cận cảnh động trung bình 14,72 ms, p95 17,01 ms.
Đây là thời gian render thử, không phải cam kết FPS hoặc CPU toàn laptop.
Camera/cử chỉ tay thật chưa được bật trong đợt này.
