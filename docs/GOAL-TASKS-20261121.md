# Alex — tác vụ web, ứng dụng và tệp

Ngày kiểm thử: 21/11/2026 (Asia/Bangkok).

## Mục tiêu và trạng thái

Người dùng muốn Alex nhận mục tiêu rồi thực hiện công việc, ưu tiên web, ứng dụng và tệp trên máy. Đã cài thay đổi vào cả mã nguồn và runtime; đã chạy lại Alex và kiểm thử từ chính cửa sổ trò chuyện, dùng Gemma cục bộ và các công cụ thật.

Đây là nâng cấp cho luồng tác vụ nhiều bước. Không phải cam kết thực hiện được mọi yêu cầu hay mọi giao diện.

## Thay đổi

- `pet/controller.py`: nhận diện mục tiêu nhiều bước trước khi bộ mở app/web tiêu thụ phần đầu câu. Giữ nguyên câu gốc cho Plan. Các lệnh đơn đã có bộ xử lý trực tiếp tiếp tục dùng đường cũ. Dùng chung luồng phản hồi, giọng nói và bộ nhớ phiên.
- `pet/task_intent.py`: phân biệt yêu cầu thao tác với câu hỏi, tiêu đề và nội dung tìm kiếm có trích dẫn. Giữ các lệnh nguồn và lệnh thiếu tên đích ở bộ xử lý hiện có.
- `pet/task_tools.py`: bộ schema gọn cho tác vụ. InspectUI cung cấp mã điều khiển tạm thời; ClickUI/TypeUI/ScrollUI đổi mã thành tọa độ từ quan sát thật. Mã cũ bị thu hồi sau thay đổi; tọa độ do model tự đưa thêm bị bỏ qua. Backend MCP vẫn kiểm tra kế hoạch, cửa sổ và đích mới nhất.
- `pet/gemma.py`: chiếu các công cụ UI cho model nhỏ, cập nhật enum mã đích sau mỗi lần quan sát, tự đọc lại trước Finish nếu model bỏ qua bước này. Việc nhập chữ cần đọc lại đúng nội dung đã nhập. Chỉ chuẩn hóa bằng chứng thành chuỗi thực sự có trong quan sát mới. Không coi kế hoạch hoặc lời tự nhận của model là thao tác đã hoàn tất.
- `pet/gemini.py`: trước Plan chỉ mở công cụ lập kế hoạch/khám phá/đọc giao diện. Riêng tác vụ dùng temperature mặc định 0.1; trò chuyện giữ cấu hình 0.65. Dừng sau lỗi thao tác, không gọi tiếp hành động cùng lô và không suy luận lại để tự lặp hành động chưa rõ kết quả.
- `pet/agent_dispatch.py`: kiểm tra ô trống cũng nhận dạng trường hợp mở ứng dụng rồi nhập chữ. Vùng soạn thảo loại Document không được đưa vào bộ ghép ref chỉ hỗ trợ các vai trò ô nhập; chọn backend nhập hiện có trước khi thử, qua cùng DesktopGuard. Không chuyển backend sau một lần giao chưa rõ kết quả.
- `desktop_mcp.py`: thêm mã pha kỹ thuật cho lỗi agent-desktop. Không thêm nội dung màn hình hoặc lời nói vào chẩn đoán mới.

Không đổi model, STT, giọng đọc, tính cách trò chuyện, danh mục ứng dụng/web, dữ liệu học, cấu hình điện thoại hay chính sách nguồn. `privacy.save_transcripts` vẫn là `false`.

## Kết quả chạy thật qua cửa sổ Alex

| Ca | Chuỗi công cụ thật | Kiểm chứng độc lập | Kết quả |
|---|---|---|---|
| Tạo tệp mới với nội dung “Nhớ học bài”, rồi đọc lại | Plan → FileSystem write → FileSystem read → Finish | Tệp tồn tại, nội dung UTF-8 đúng hoàn toàn; Alex trả lời đúng | Đạt |
| Mở trang mẫu trên Chrome rồi bấm nút Tìm kiếm | Plan → App/OpenWeb → Snapshot → Click → Snapshot → Finish | Trang chuyển từ “Chưa tìm kiếm” sang “Đã tìm kiếm”; Alex xác nhận | Đạt |
| Mở Notepad rồi nhập dấu thử vào ô văn bản | Plan → App → Snapshot → Type → Snapshot → Finish | Tab thử chứa đúng `alex-test-20261121`, dài 18 ký tự; Alex xác nhận | Đạt |

Tệp thử: `C:\Users\Admin\OneDrive\Tài liệu\ChatGPT\alex\alex-goal-tasks-20261120\file-fixture\alex-live-20261121.txt`.

Các ca dùng dữ liệu mẫu. Không gửi tin nhắn, không thử xóa/ghi đè tệp người dùng, không thực hiện thao tác nguồn/đăng nhập. Tài liệu người dùng đã mở không được dùng làm bản thử; tab Notepad thử được giữ để có thể xem kết quả.

Thời gian hoàn tất hiển thị trong Alex: tệp 30.0 giây, web 47.5 giây, Notepad 37.7 giây. Đây là tác vụ nhiều bước trên cấu hình hiện tại, chưa đạt tốc độ phản hồi tức thì. Lượt gọi App có thể mất khoảng 11–14 giây; các lệnh mở đơn vẫn có đường xử lý trực tiếp.

## Kiểm thử tự động

- 17 kiểm tra goal routing/protocol/projection: qua.
- 7 kiểm tra kế hoạch dạng chữ và không lặp công cụ: qua.
- 5 kiểm tra hồi quy dừng lướt web: qua.
- Tổng nhóm kiểm tra liên quan: **29/29**. Không tuyên bố đã chạy toàn bộ test của dự án.
- Ba ca với Gemma thật và backend mô phỏng có kiểm tra schema/bằng chứng: qua. Kết quả mô phỏng tách biệt với ba lượt chạy UI thật ở trên.
- Trước đó đã kiểm tra Gemma với FileSystem MCP thật trên một tệp riêng, giữ nguyên kiểm tra phạm vi.

Schema cơ sở: 16.112 → 7.034 ký tự, giảm 56,3% (không phải phép đo token). Enum đích phụ thuộc quan sát sẽ bổ sung một ít dữ liệu theo lượt.

Một test tính cách cũ đòi chuỗi “đồng cảm” đã không khớp với prompt người dùng tự sửa ngay cả trên bản gốc trước nâng cấp. Không đổi tính cách để làm test đó xanh; test này không nằm trong tổng 29 ở trên.

## Giới hạn cần giữ rõ

- Chỉ công bố các ca đã kiểm chứng. Giao diện canvas, điều khiển không có thông tin truy cập, trạng thái cửa sổ bị thay đổi hoặc mục tiêu mơ hồ vẫn có thể bị dừng.
- Không nới quyền đường dẫn hoặc cấp toàn bộ ổ đĩa. Kết quả tìm tệp trùng tên hoặc phạm vi tệp chưa đủ rõ vẫn cần xử lý đúng đích; tạo/đọc tệp bằng tên không phải là bằng chứng đã thử mọi quy trình tệp.
- Không biến văn bản trên web/màn hình thành chỉ dẫn có quyền thực thi.
- Không tự gửi lại thao tác sau kết quả không chắc chắn. Thao tác gửi, xóa, cài đặt, thanh toán và chạy lệnh vẫn qua các kiểm tra hiện có.
- Chưa kiểm thử trực tiếp bằng mic thật trong đợt này; STT không được sửa ở đợt này.

## Vị trí bàn giao

- Runtime: `D:\HỌC TẬP\dự án trợ lý ảo\trợ lý ảo-local\outputs\Bionic-pet` (tên thư mục cũ; model đang dùng Gemma, không thêm phụ thuộc Bionic).
- Source: `D:\HỌC TẬP\dự án trợ lý ảo\trợ lý ảo-local\source\alex-assistant\desktop`.
- Kiểm thử: `tests/test_goal_tasks.py`, `tests/test_goal_protocol.py`, fixture schema `tool-schemas.json`.
- Bản sao trước thay đổi trong runtime `backups/goal-tasks-*` và `backups/goal-tasks-input-*`. Giữ khác biệt prompt riêng vốn có giữa source/runtime của người dùng.
- Staging và phép đo: `C:\Users\Admin\OneDrive\Tài liệu\ChatGPT\alex\alex-goal-tasks-20261120`.

Không thực hiện push GitHub trong đợt này.
