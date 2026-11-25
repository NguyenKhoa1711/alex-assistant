# Alex — sửa luồng mở Messenger rồi tìm kiếm, 21/11/2026

Trạng thái cuối: **một ca Messenger đầu-cuối trên giao diện thật đã đạt**. Không suy diễn thành mọi ứng dụng, mọi tác vụ hoặc mọi câu nói đều đã được kiểm chứng.

Người dùng đã đổi phân công từ “Antigravity sửa, Codex kiểm tra” sang yêu cầu Codex trực tiếp làm tiếp. Các sửa dưới đây được cài đồng bộ vào source và runtime sau kiểm thử, có backup. Không thay tính cách riêng do người dùng chỉnh, STT/TTS, API keys hoặc cấu hình ghép nối.

## Những lỗi đã xác định và sửa

1. `GoalUIReferences` đã hiểu `[focused]` nhưng `DesktopGuard._target_line` và bộ nối ref của `agent_bridge` vẫn không nhận thuộc tính đứng trước `[action:]`. Đồng bộ bộ phân tích, so khớp đúng tọa độ đầu dòng; giữ kiểm tra cửa sổ, fresh snapshot, live target và trường hợp nhiều control không phân biệt được.
2. Vai trò UIA thực tế là `combo box`, còn bộ chọn ô search so với `combobox`. Chuẩn hóa tên vai trò, chỉ cho phép ô nhập thực; không dùng nút search, lịch sử, thanh địa chỉ hoặc ô soạn làm đích Type. Khi không tìm được ô search thì không cho Type rơi sang trường khác. Truy vấn phải khớp câu yêu cầu.
3. Cầu `desktop_mcp.py` dùng `Path` nhưng thiếu import, gây `NameError` ngay ở Snapshot. Bổ sung import và bài kiểm tra thực thi chính handler với backend/cửa sổ giả. Test đối chứng bỏ Path xác nhận bắt được đúng lỗi.
4. Native Type báo thành công nhưng chuỗi mẫu trên màn hình có ký tự khác với yêu cầu. Thêm `pet/search_ui.py`: bước nhập search được chuyển sang agent-desktop sau các kiểm tra guard/live target, chọn cách nhập trước khi gửi, chỉ tác động đúng ref trường tìm kiếm và query tường minh. Không gửi Enter, không nhập vào draft, không chuyển backend hoặc thử lại sau kết quả không chắc chắn.
5. Sau input, đọc lại giá trị trường bằng ref mới, cùng cửa sổ. Snapshot chỉ có thêm bằng chứng `Verified search field value` nếu một lượt đọc MỚI khớp query; không dùng riêng trạng thái “đã gõ” làm bằng chứng.
6. Với yêu cầu đơn giản mở rồi tìm kiếm, sau khi đọc đúng query chỉ cung cấp Finish/Cancel để model không bấm thêm mục ngoài yêu cầu. Sau Finish chỉ sinh câu trả lời. Khi đã nhập thì không tự Type lại trong lúc chờ readback; số lần đọc lại được giới hạn.
7. Bổ sung phân loại lỗi kỹ thuật hữu hạn (`MCP_ERROR ... type=...`) và cờ `verified_search`, bỏ việc ghi nguyên exception trong nhánh gọi công cụ. Không bật lưu transcript hoặc lưu màn hình vào log.

## Kiểm chứng thực tế

Câu mẫu gõ qua cửa sổ Alex, mic tắt:

> Mày hãy mở Messenger cho tao và tìm kiếm alex-kiem-tra.

Nhật ký 21/11/2026, giờ Việt Nam/Thái Lan:

```text
12:59:16 router_match goal_task
12:59:22 Plan error=False
12:59:25 OpenLocal error=False
12:59:47 Snapshot error=False; search_fields=1
12:59:50 Type preflight loại clear=True, enter=True không được yêu cầu
13:00:02 Type error=False
13:00:08 Snapshot error=False; search_fields=1; verified_search=True
13:00:11 Finish error=False
```

Kiểm tra độc lập bằng Computer Use: có ô “Tìm kiếm trên Messenger”; chuỗi mẫu xuất hiện đúng trong kết quả tìm kiếm qua dữ liệu truy cập giao diện. Alex hiển thị:

> Tao đã mở Messenger cho mày và tìm kiếm alex-kiem-tra. Mày xem kết quả đi nhé!

Giao diện Alex hiển thị **57,1 giây**. Đây là kết quả một lượt nhiều bước, gồm tải trang và thao tác/readback; chưa nhanh và không phải benchmark ổn định. Không gửi tin nhắn, không bấm người nhận hay nút gửi trong lượt đạt. Không dùng tên hoặc nội dung riêng của người dùng làm dữ liệu thử.

## Kiểm thử tự động

Đã chạy độc lập trên **runtime 58/58 OK** và **source 58/58 OK**:

- `tests.test_goal_tasks`
- `tests.test_goal_protocol`
- `tests.test_desktop_guard`
- `tests.test_search_execution_contract`
- `tests.test_mcp_snapshot_route`
- `tests.test_search_control_roles`
- `tests.test_verified_search_input`
- `tests.test_search_completion_stop`

Các kiểm tra tự động dùng cửa sổ/backend giả; kết quả UI thật tách riêng ở mục trên. Không tuyên bố đã chạy toàn bộ test của dự án. Cảnh báo `AGENT_FOCUS_FAIL` trong một test là nhánh âm cố ý để xác nhận không fallback khi focus chưa được xác minh.

## Vị trí và bàn giao

- Runtime: `D:\HỌC TẬP\dự án trợ lý ảo\trợ lý ảo-local\outputs\Bionic-pet`
- Source: `D:\HỌC TẬP\dự án trợ lý ảo\trợ lý ảo-local\source\alex-assistant\desktop`
- Staging và script cài có kiểm tra thay đổi đồng thời: `C:\Users\Admin\OneDrive\Tài liệu\ChatGPT\alex\alex-final-search-20261121`
- Backup gần nhất: runtime `backups/search-finish-stop-20261121-125816`. Các giai đoạn trước có backup `search-focused-*`, `mcp-technical-errors-*`, `mcp-path-import-*`, `search-native-roles-*`, `verified-search-*`.

Alex đã được nạp lại và đang chạy bản mới; mic vẫn tắt trong lúc kiểm thử. Không push GitHub trong đợt sửa này.

## Giới hạn còn lại

- Chưa kiểm thử mic thật trong đợt này; không khẳng định STT nghe đúng mọi tên ứng dụng/người nhận.
- Ca đạt là tìm kiếm trên Messenger, không phải chứng minh luồng gửi tin nhắn đã hoạt động hay đã kiểm chứng người nhận/tin gửi.
- Đích không có thông tin truy cập, trùng ref, đổi cửa sổ, readback sai hoặc chưa xác định được kết quả vẫn dừng. Không bỏ kiểm tra quyền để cố hoàn tất.
- Tốc độ còn cần tối ưu. Giữ chứng minh kết quả thực, không bỏ readback để giảm số đo.
