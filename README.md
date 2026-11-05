# Alex Assistant

Mã nguồn trợ lý Alex trên Windows và Android. Alex sử dụng Gemma chạy cục bộ để trò chuyện; phần tra cứu web được gửi tới dịch vụ tìm kiếm khi cần. Các thành phần Bionic cũ được giữ trong mã nguồn để tham khảo và tương thích.

## Thành phần

- `desktop/`: giao diện pet, microphone/VAD/STT, giọng nói, router ứng dụng/tệp/web, thao tác cửa sổ, âm lượng/độ sáng, kết nối điện thoại.
- `android/`: trò chuyện, ghép QR/TLS, mở khóa qua mạng hoặc Bluetooth và cảnh báo theo cấp.
- `windows-unlock/`: mã nguồn dịch vụ mở khóa quyền LocalSystem, kiểm chứng giao diện Windows và gửi PIN một lần; có bộ gỡ cài đặt.
- `windows-display-priority/`: ưu tiên tắt màn hình tạm thời khi Alex khóa máy và phục hồi khi mở khóa.
- `mcp/`, `docs/`: công cụ cục bộ và tài liệu tích hợp.
- `tools/`: kiểm thử và kiểm tra phục hồi.

## Bản nguồn và bản đang chạy

Repo này dùng để phát triển/khôi phục. Pet đang chạy tại `../../outputs/Bionic-pet`; việc sửa repo không tự triển khai vào bản đang chạy.
Các thay đổi đồng bộ có thể xem bằng `git diff`. Không đưa cấu hình, dữ liệu người dùng hoặc khóa vào commit.

## Kiểm tra

Các bài thử desktop ở `desktop/tests`; các thao tác nguồn điện, mở ứng dụng và nhập phím được giả lập. Bộ thử Android thuần Java kiểm tra giữ để nói, thu âm, cảnh báo, xác nhận, hủy, hết hạn, TLS và nguyên tắc không gửi lại PIN. Xem `docs/AUDIT-20261105.md` để biết kết quả và giới hạn kiểm thử mới nhất.

`tools/Test-UnlockClient.ps1 -JdkRoot <JDK>` chạy kiểm thử client không cần Android SDK hay điện thoại.
`windows-unlock/run-windows-lab.ps1` biên dịch và chạy bộ thử C# mà không cài dịch vụ hay gửi phím thật.

## Android

Xem `android/README.md`. APK người dùng đã cài và khóa ký được lưu riêng ngoài repo. Bản biên dịch kiểm thử dùng khóa tạm không cài lên điện thoại và không thay thế khóa phát hành.

## Thiết lập model cục bộ

Sao chép `desktop/config.example.yaml` thành `desktop/config.yaml`, chỉnh `llm.gemma_model_path` thành đường dẫn tuyệt đối tới tệp GGUF Gemma đã cài và điều chỉnh số lớp GPU theo phần cứng. Model, bộ chạy và cấu hình cá nhân không nằm trong Git; xem `desktop/GEMMA-LOCAL.md` để biết thêm chi tiết.

## Hành vi và quyền riêng tư

- Đóng tab chỉ đóng một tab; đóng cửa sổ/ứng dụng là lệnh riêng.
- Tắt máy: theo cấu hình nguồn điện hiện tại. Chế độ chờ mở khóa từ xa khi cắm sạc khóa Windows/tắt màn hình và giữ tiến trình hoạt động; không phải Sleep thật qua nút nguồn Windows.
- Tắt nguồn là Shutdown; lệnh nguồn không tự lặp sau khi mở khóa.
- PIN chỉ tồn tại tạm thời cho một lần xác nhận trên điện thoại, không được lưu hoặc ghi log.
- Đợt này không bổ sung đánh thức Sleep thật qua Internet và không gửi thử cảnh báo Zalo/SMS.
- Không commit model, venv, profile Bionic, log, bản thu, khóa ký, chứng chỉ riêng, thông tin ghép nối hoặc cấu hình cá nhân.
