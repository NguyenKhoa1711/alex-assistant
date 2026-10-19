# Kiểm tra bản nguồn

Các kiểm thử Python nhỏ dùng `unittest`, mock tác vụ hệ thống và thư mục tạm. Một số bài thử giao diện cũ nhận thêm đường dẫn project ở tham số thứ nhất; không chạy gộp toàn bộ bằng discovery khi chưa đọc cách gọi.

Ví dụ từ `desktop/`, với môi trường đã cài phụ thuộc:

```powershell
python -m unittest discover -s tests -p test_close_actions.py
python -m unittest discover -s tests -p test_background_launcher.py
python -m unittest discover -s tests -p test_incomplete_open.py
```

`android/tests/build-tests.ps1` biên dịch và đóng gói bài thử riêng; truyền `-ProjectRoot` và `-AndroidJar`. Các bài thử thiết bị chỉ chạy khi có điện thoại được phép kiểm tra. Không chạy lệnh ngủ/tắt nguồn hay gửi SMS/Zalo thật trong kiểm thử tự động thông thường.
