# Alex: rút ngắn khoảng chờ giữa các câu — 21/11/2026

## Yêu cầu và phạm vi

Người dùng muốn Alex nói nối câu tự nhiên hơn, không im vài giây giữa các đoạn. Giữ giọng Thái Sơn, tốc độ giọng hiện tại, tính cách riêng, STT/VAD, lịch sử phiên, ghép nối và `privacy.save_transcripts: false`.

## Nguyên nhân và bản sửa đã cài

- `TurboSpeaker.speak_sequence` trước đây chỉ stream câu đầu; các câu sau phải đợi tổng hợp trọn câu trước khi đưa âm thanh vào hàng phát. Câu sau dài gây khoảng chờ lớn.
- Nay stream mọi câu trong cùng một luồng phát; giữ khóa phát, bộ nhớ đệm và cơ chế ngắt.
- Thêm `pet/speech_pcm.py`: rút im lặng thừa ở biên mỗi câu, giữ tối đa 40 ms đầu và 100 ms cuối với ngưỡng int16 bằng 32; giữ nguyên khoảng nghỉ bên trong câu, kể cả qua ranh giới các gói stream.
- Ngưỡng nạp lại âm thanh khi hàng phát cạn: 0,6 → 0,25 giây; đệm ban đầu vẫn 1 giây.
- `HybridSpeaker` rút biên âm thanh và giảm khoảng đệm giữa các ngôn ngữ từ 80 xuống 40 ms; giữ giọng bản ngữ Anh/Trung.
- Đã đồng bộ runtime và source: `pet/tts_turbo.py`, `pet/polyglot_tts.py`, `pet/speech_pcm.py`, `tests/test_speech_flow.py`.
- Bản sao trước sửa: `outputs/Bionic-pet/backups/speech-flow-20261121-132618`.

## Kiểm thử và số đo thật

`tests.test_speech_flow` + `tests.test_multilang_tts`: **15/15 đạt trên runtime**, **15/15 đạt trên source**. Bao gồm rút biên nhưng giữ nghỉ nội câu, mọi câu đều stream, một luồng phát, bộ đệm, hủy phát và giọng đa ngôn ngữ.

Đo trên worker Thái Sơn offline thật và `sounddevice.OutputStream` thật, dùng cùng ba câu mẫu tổng hợp; dừng Alex trong lúc đo để mic không thu lại loa. Không thu âm người dùng hoặc gửi dữ liệu ra mạng.

| Mẫu câu sau dài | Trước | Sau |
| --- | ---: | ---: |
| Tổng thời gian phát đo được | 24,047 s | 17,516 s |
| Thời gian đến âm thanh đầu | 0,875 s | 0,985 s |
| Khoảng chờ lớn nhất giữa hai lần ghi âm thanh | 6,922 s | 0,016 s |
| Underflow do PortAudio báo | 0 | 0 |

Khoảng chờ giữa lần ghi là số đo của bên cấp âm thanh, không đồng nghĩa chính xác khoảng im lặng người nghe cảm nhận. Đây là một lượt A/B cho mẫu dài; không bảo đảm mọi câu đạt tốc độ tương tự. Bản sửa nhắm giảm gián đoạn sau khi bắt đầu nói, không chứng minh giảm độ trễ trước câu đầu. Mẫu toàn câu ngắn: tổng thời gian 12,625 → 12,250 s.

Mã đo và kết quả JSON/WAV mẫu nằm trong workspace `alex-speech-flow-20261121`. WAV nối các khối PCM không thể hiện các khoảng chờ theo đồng hồ.

## Trạng thái chạy và giới hạn xác minh

- Alex đã khởi động lại, log READY 13:26:39; Thái Sơn, mic tắt.
- Đã gửi câu mẫu “Kể một chuyện vui ngắn gồm ba câu về con mèo đi học.” từ GUI, bật tạm “Đọc câu trả lời khi gõ”. Log 13:28:34 có hoàn tất Gemma và số đo Thái Sơn, không có lỗi ở lượt đó.
- Sau đó người dùng nhấn Esc dừng Computer Use; chưa đọc được kết quả cuối trên GUI và chưa khôi phục ô “Đọc câu trả lời khi gõ” về trạng thái tắt ban đầu. Không tiếp tục thao tác giao diện sau Esc.
- Không sửa cấu hình cá nhân, không đẩy GitHub trong lượt này.
