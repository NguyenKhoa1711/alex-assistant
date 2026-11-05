# Trạm chỉ huy — khuôn mặt theo clip FatihMakes

Cập nhật 29/10/2026 theo yêu cầu dùng khuôn mặt trong
[Jarvis Mark 54 — With a New Face](https://www.youtube.com/shorts/Cwt-Jz6-sEw).
Mẫu hiện tại là mặt người 3D xanh lam, bề mặt tam giác, mắt phát sáng, có mũi,
môi và xương hàm từ chính mô hình tác giả công khai. Thay mẫu robot bo tròn.

- Mic tắt: mặt dịu, mắt khép. Đang nghe: mắt xanh và hướng về người dùng.
- Suy nghĩ: mắt vàng, ánh nhìn lệch nhẹ. Đang nói: mắt cam, môi/hàm chuyển động.
- Chớp mắt, nghiêng đầu nhẹ và nhìn theo chuột. Giảm chuyển động giữ hình tĩnh.
- Miệng hiện chuyển động theo trạng thái đang nói, chưa khớp từng âm vị/PCM.
- Chỉ đổi portrait trong Trạm chỉ huy. Các lệnh, mic, TTS, Vũ trụ, APK và pet
  nổi trên desktop giữ nguyên. Không mở thêm mic/camera hoặc gọi dịch vụ mạng.

## Mã và nguồn

`pet/reference_portrait.py`: adapter QWidget cho Alex; `hologram_face.py`: API
tương thích. `pet/vendor/fatih_hologram`: avatar.py, avatar_mesh.py và face_model.obj
từ [FatihMakes/Mark-LVI](https://github.com/FatihMakes/Mark-LVI), commit
`4d4035c1b40a3bc796ac63f2f1b6a99bc0dd334d`. Chỉ dùng bộ vẽ cục bộ.

Renderer **CC BY-NC 4.0**, Copyright 2026 FatihMakes. Mô hình MediaPipe **Apache-2.0**.
Giấy phép đầy đủ và các thay đổi ghi tại `pet/vendor/fatih_hologram/NOTICE.md`.
Giữ ghi nguồn khi chia sẻ; không coi renderer này là mã cho phép dùng thương mại.
Không có xác nhận hay bảo trợ của tác giả cho bản tích hợp Alex.

Điều chỉnh: PyQt6 → PySide6, import tương đối, áp dụng độ khép mí `_lids`
đúng trạng thái. Tất cả dữ liệu mặt đóng gói tại chỗ, không cần tải lúc chạy.

## Hiệu năng và kiểm tra

Timer 33 ms (tối đa khoảng 30 fps), giới hạn dt sau Sleep, dừng khi ẩn/minimize
hoặc chọn Giảm chuyển động. Chỉ giữ một mesh và một ảnh cache của pose hiện tại.
NumPy và PySide6 đã có sẵn; không thêm dependency nặng.

Kết quả mới nhất nằm trong `hologram-tests.json` và báo cáo triển khai; kiểm tra
Qt offscreen bao gồm trạng thái, bố cục, cache, reduced motion và vòng đời timer.
Ảnh thực tế sau khởi động lại nằm trong báo cáo cùng `deployment.json`.
Bản robot cũ và các thiết kế trước được giữ trong thư mục sao lưu của dự án.
