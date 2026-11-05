# Alex: Gemma chạy trên laptop

## Kiểm tra nghe tiếng Việt (03/11/2026)

- Theo yêu cầu cải thiện nghe, giữ Whisper Medium trên CUDA và tăng `stt.beam_size` từ 1 lên 3, giữ nguyên các ngưỡng loại âm thanh thiếu tin cậy và `privacy.save_transcripts: false`. Giữ E4B, mic Realtek WASAPI và giọng Thái Sơn.
- Đã thử đúng năm câu tổng hợp Thái Sơn: Medium beam 1 có 6 lỗi từ/36 từ, beam 3 có 4/36; trung bình trong thử tách biệt 0,33 và 0,36 giây. Whisper large-v3-turbo có 4/36 ở cả hai beam, nhưng các lỗi khác nhau; model thử đã dọn vì không có bằng chứng đủ mạnh để chuyển. Đây là mẫu rất nhỏ, không đại diện giọng người dùng và không chứng minh cải thiện ngoài thực tế.
- Cả hai model vẫn nghe sai câu KiCad tổng hợp; không tự đoán thêm biệt danh hoặc thay ngưỡng an toàn. Đã nhờ người dùng thử giọng thật. Cấu hình trước sửa lưu trong `Luu-tru/alex-stt-accuracy-20261103`.


## Trạng thái mới nhất: Gemma 4 E4B (03/11/2026)

- Theo yêu cầu của người dùng, Alex chuyển từ 12B sang Gemma 4 E4B Q4_K_M tại `Alex-data/lmstudio/models/lmstudio-community/gemma-4-E4B-it-GGUF/gemma-4-E4B-it-Q4_K_M.gguf` (5.335.291.936 byte, SHA-256 `0ffb122c8b6921f13cbc34186e052524d0b5803b17f4867b7197a561400b3770`). Model chạy cục bộ tại localhost.
- `gemma_gpu_layers: 42`, `gemma_gpu_fallback_layers: 32`; đã xác nhận E4B và Whisper Medium sẵn sàng trên CUDA. Bộ lọc an toàn và luồng công cụ giữ nguyên. Không thay giọng Thái Sơn, bộ nghe, hay lưu nội dung giọng nói.
- Hai câu trò chuyện mẫu qua `GemmaChat` khi Whisper sẵn sàng hoàn tất trong khoảng 1,4 và 0,9 giây; thời gian nghe/phát tiếng thực tế sẽ lâu hơn. Chưa xác nhận bằng giọng thật sau chuyển đổi.
- Tệp trọng số 12B đã được xóa theo yêu cầu. Cấu hình cũ được sao lưu ở `Luu-tru/gemma-e4b-migration-20261103`, nhưng không khôi phục đường dẫn 12B nếu chưa tải lại model. Các phần dưới mô tả các cấu hình 12B/E2B lịch sử.


## Cập nhật gần nhất: hạn chế giọng ngắt quãng (03/11/2026)

- Người dùng báo Alex phát một đoạn rồi ngừng nhiều giây trong khi chờ Gemma 12B. Đã khôi phục `SentenceBuffer` về ngưỡng chia theo mệnh đề trước lần tối ưu gần nhất, và hướng dẫn model trả lời một câu ngắn cho lời chào/trò chuyện đơn giản; câu cần giải thích vẫn có thể dài.
- `pet/gemma.py` hiện gửi tối đa hai lượt hội thoại gần nhất, tối đa 900 ký tự lịch sử trong hội thoại thường; giữ nguyên câu hiện tại, và không rút gọn payload dùng công cụ. Model có thể không thấy chi tiết cũ hơn. Mức GPU 24, dự phòng 20 được giữ.
- Câu thử đơn lẻ sau sửa: chào hỏi hoàn tất khoảng 13,5 giây, phép tính khoảng 4,5 giây; không đảm bảo tốc độ/độ liền mạch mọi lúc. Chưa xác nhận bằng giọng thật sau sửa. Bản trước nằm tại `Luu-tru/alex-voice-continuity-20261103`.
- Các mô tả phía dưới về bốn lượt lịch sử hoặc chia mệnh đề sớm là lịch sử, không phải trạng thái mới nhất.


## Cập nhật gần nhất: giảm chờ giọng nói (03/11/2026)

- Người dùng chọn giữ Gemma 12B. Cấu hình hiện tại `gemma_gpu_layers: 24`, `gemma_gpu_fallback_layers: 20`; `GemmaChat.check_ready` tự thử lại 20 lớp nếu tiến trình mức 24 thoát trước khi sẵn sàng. Sau khi nạp cùng Whisper, GPU còn khoảng 736 MiB; cần theo dõi nếu có ứng dụng đồ họa khác dùng GPU.
- Trong phép đo cùng câu giả lập và 4096 context, mức 20 lớp trả lời 4,0 giây, mức 24 lớp 3,3 giây. Đây là phép đo đơn lẻ, không bảo đảm tốc độ với mọi câu.
- `pet/wake.py` phát sớm hơn ở ranh giới mệnh đề khi đủ dài, trong khi model tiếp tục sinh; văn bản hiển thị không bị thay đổi. Ở cuối mỗi lượt Alex vẫn đóng mic khi đang nói để tránh tự nghe giọng của mình; đây chưa phải hội thoại song công thời gian thực.
- Bản cũ được sao lưu trong `Luu-tru/alex-live-speed-20261103`. Các mô tả `gemma_gpu_layers: 20` ở dưới là trạng thái lịch sử.


## Tối ưu hội thoại 12B (03/11/2026)

- `pet/gemma.py` rút gọn chỉ dẫn cho hội thoại thông thường và chỉ gửi tối đa bốn lượt hội thoại gần nhất, tổng tối đa 1.600 ký tự lịch sử. Câu hỏi hiện tại không bị cắt; lịch sử đầy đủ vẫn được giữ theo cấu hình trong bộ nhớ tiến trình. Ngữ cảnh cũ có thể không được model thấy ở lượt trò chuyện tiếp theo.
- Không rút gọn payload của các lượt dùng công cụ, nên các chỉ dẫn và kết quả công cụ được giữ nguyên. Trong một lượt thử giả lập giống nhau, thời gian đến token đầu giảm từ 7,64 giây xuống 4,72 giây; đây không phải cam kết tốc độ cho mọi câu. Kiểm tra bằng giọng nói thật vẫn cần người dùng thử.
- Tệp trước tối ưu được sao lưu trong `Luu-tru/gemma12-fast-chat-20261103`.


## Cập nhật mới nhất: Gemma 4 12B (03/11/2026)

- Người dùng chọn Gemma 4 12B Q4_K_M chạy cục bộ trong Alex. Model ở `Alex-data/lmstudio/models/lmstudio-community/gemma-4-12B-it-GGUF/gemma-4-12B-it-Q4_K_M.gguf`, 7.381.382.944 byte, SHA-256 `95d83ba36642b1f385fb906b5962a71763361be3bac930a709945f72d97473f8`.
- `llm.gemma_gpu_layers: 20` cho phép chia model giữa GPU và RAM. `pet/gemma.py` giữ cổng localhost 18440, ngữ cảnh 4096 và đọc số lớp GPU từ cấu hình. Whisper Medium, giọng nói và công cụ Windows được giữ.
- Đã thử model độc lập và thử lại qua `GemmaChat` khi bộ nghe đã sẵn sàng: câu mẫu trả lời đúng, lượt đầy đủ khoảng 17,2 giây. Tốc độ và RAM phụ thuộc tải máy; kiểm tra tác vụ và giọng thật trước khi kết luận mọi tính năng hoạt động.
- Theo yêu cầu, đã xóa tệp trọng số E2B, Qwen3.5-4B, Whisper Small và PhoWhisper Small; muốn quay về phải tải lại. Công cụ so sánh mic cũ không còn hai model small. Bản sao cấu hình/mã trước nâng cấp nằm trong `Luu-tru/gemma12-upgrade-20261103`; không khôi phục cấu hình E2B nếu chưa tải lại model.
- Các mục bên dưới mô tả lịch sử E2B, không phải cấu hình hiện tại.


Cập nhật ngày 03/11/2026 cho người tiếp tục bảo trì dự án Alex, bao gồm Antigravity.

- Alex dùng Gemma 4 E2B Q4_K_M cục bộ qua `llm.provider: gemma`. Tệp GGUF nằm tại `Alex-data/lmstudio/models/lmstudio-community/gemma-4-E2B-it-GGUF/gemma-4-E2B-it-Q4_K_M.gguf` trong thư mục dự án; SHA-256 là `71e6e8cb64a76da1a734fb8f6ba389d2784950d9902f5e87244fca0a15190c94`.
- `pet/gemma.py` chạy `llama-server.exe` từ bộ chạy đã cài, lắng nghe `127.0.0.1:18440` với tên model `alex-gemma`. Model được khởi động nền cùng pet. Không cần mở Bionic và không gọi Gemini API để xử lý yêu cầu mặc định.
- `GemmaChat` dùng lại luồng công cụ, ngữ cảnh và tính cách trong `pet/gemini.py`; giao tiếp chỉ cho phép địa chỉ loopback, không gửi khóa Gemini. Công cụ Windows dùng `DesktopMCP` hiện có và các quyền/kiểm tra của Alex. Nếu model không gọi công cụ hoặc công cụ báo lỗi, Alex không tự nhận hoàn tất.
- `pet/controller.py` chọn Gemma khi `llm.provider` bằng `gemma`, khởi động model và công cụ nền, giữ router, STT, giọng Thái Sơn và kết nối điện thoại. Cấu hình Gemini cũ và khóa của người dùng được giữ lại, không tự dùng làm dự phòng.
- Cấu hình `llm` ở cả mã nguồn và bản chạy đặt `base_url` là `http://127.0.0.1:18440`, `model` là `alex-gemma` và đường dẫn GGUF vào `gemma_model_path`. Cấu hình còn lại được giữ theo từng bản.
- Máy tại thời điểm thử: Dell Precision 7550, RAM khoảng 16 GB, GPU Quadro RTX 3000 6 GB. Trong câu mẫu cục bộ sau triển khai, Gemma trả lời phép tính trong khoảng 1,2 giây; kết quả thay đổi theo tải máy. Đã kiểm tra tìm thư mục thật ở chế độ chỉ đọc qua danh sách công cụ đầy đủ. Model nhỏ có thể kém Gemini trong các yêu cầu phức tạp; kiểm tra kết quả trước khi báo đã làm.
- Sáu kiểm tra tự động bao gồm chọn provider, giới hạn loopback, không chuyển ra Gemini API, không chiếm cổng của ứng dụng khác, và không báo thành công khi chưa gọi công cụ hoặc công cụ báo lỗi. Chưa thay thế việc người dùng thử giọng nói thật và các tác vụ phức tạp.
- Bản sao trước chuyển đổi nằm tại `Luu-tru/gemma-local-20261103/{source,runtime}`. Mỗi thư mục giữ `config.yaml`, `controller.py`, `window.py` tương ứng; giữ nguyên bản sao và xem xét thay đổi mới trước khi khôi phục. Không xóa model hoặc thư mục dự án tự động.

## Sau khi gỡ Bionic

- Ngày 03/11/2026, theo yêu cầu của người dùng, ứng dụng Bionic đã được gỡ bằng trình gỡ của Windows. Alex vẫn chạy Gemma cục bộ; đã thử một câu mẫu sau khi gỡ và nhận câu trả lời.
- Dữ liệu đã chuyển từ `Bionic-data` sang `Alex-data`, gồm model Gemma, bộ chạy cục bộ, giọng nói, công cụ Windows và hồ sơ Bionic cũ. Liên kết `%USERPROFILE%/.lmstudio` trỏ đến `Alex-data/lmstudio`. Không xóa hoặc đổi tên các đường dẫn này nếu chưa cập nhật và kiểm tra đầy đủ các thành phần phụ thuộc.
- Công cụ Windows dùng `computer.command` trỏ tới Python trong môi trường đã cài và `computer.command_args: [-m, windows_mcp]`; cách này tránh phụ thuộc vào đường dẫn cố định bên trong tệp launcher cũ.
- Lối tắt mới trên Desktop tên `Alex.lnk`; lối tắt Bionic và tên cũ `Alex va Bionic.lnk` đã được dọn. Lối tắt khởi động cùng Windows của Alex vẫn được giữ. Hồ sơ Bionic và bản sao các lối tắt trước khi gỡ nằm tại `Luu-tru/bionic-truoc-go-20261103`.
