## Vũ trụ Alex: zoom và bóc tách hành tinh (04/11/2026)

- Có chế độ **Bóc tách hành tinh** cho cả tám hành tinh, tự chuyển cảnh 700 ms, thanh Mức tách, tên/mô tả từng lớp, có thể ghép lại và chọn hành tinh khác. Các lớp là minh họa, không phải kích thước hay vị trí thực; cấu trúc các hành tinh khí/băng và một số lõi vẫn đang được nghiên cứu.
- Zoom quỹ đạo tới 600% (cũ 250%), giữ điểm dưới con trỏ khi cuộn; zoom hình bóc tách tới 300%, kéo để dịch. Có nút +/- và đặt lại góc nhìn. Cử chỉ tay tiếp tục điều khiển khung đang xem; camera chỉ bật khi chủ máy chọn.
- Cận cảnh dùng ảnh tạo ở độ phân giải phù hợp màn hình; chỉ hành tinh đang chọn xoay trong cảnh (cache một khung, 10 fps) và các lớp dao động nhẹ khi hiệu ứng đang bật. Dừng timer khi ẩn trang, thu nhỏ cửa sổ, tạm dừng hoặc tắt hiệu ứng; không tải ảnh ngoài, không gửi hình camera đi.
- File: `pet/orbit_scene.py`, `pet/planet_art.py`, `pet/planet_layers.py`, `pet/space_view.py`, `tests/test_planet_layers.py`; cập nhật giới hạn trong `tests/test_space_view.py`. Đã qua 33 bài kiểm tra, bao gồm camera giả lập, điều khiển, chuyển trang, pause, kích thước nhỏ; chưa thử cử chỉ bằng camera thật. Đo 20 khung hình cảnh minh họa ở 800x500 với hành tinh đang xoay: trung bình 11,3 ms/khung, tối đa 21,3 ms trong phiên thử offscreen, không phải cam kết fps thực tế.
- Bản trước trong `Luu-tru/alex-universe-layers-20261104`; bản source/runtime được đồng bộ, không đổi STT, model, mạng hay logic chat.
- Tài liệu NASA đối chiếu mô hình: Trái Đất https://science.nasa.gov/earth/facts/ ; Sao Mộc https://science.nasa.gov/jupiter/jupiter-facts/ ; Sao Thổ https://science.nasa.gov/saturn/facts/ ; Thiên Vương/Hải Vương https://science.nasa.gov/asset/hubble/uranus-and-neptune/ ; Sao Hỏa https://science.nasa.gov/mars/facts/ ; Sao Kim https://science.nasa.gov/mission/veritas/science/ .

## Tra cứu để trả lời câu hỏi (04/11/2026)

- Chủ dự án cho phép Alex tự tra cứu khi câu hỏi ngoài luồng cần thông tin mạng. Bộ phân loại cục bộ bảo thủ (`research_request`) chỉ chọn câu thông tin/thời sự; trò chuyện, lệnh máy, câu hỏi có dữ liệu cá nhân dễ nhận biết, mật khẩu, email, đường dẫn, phủ định đều không tự gửi đi. Bộ lọc này không bảo đảm nhận diện mọi thông tin nhạy cảm.
- Chỉ gửi câu hỏi hiện tại tới trang tìm kiếm HTML DuckDuckGo qua HTTPS, không gửi lịch sử, âm thanh, cookie hay tệp cá nhân; nhận tối đa bốn tiêu đề/đoạn trích, không tự truy cập trang kết quả. Có timeout, giới hạn kích thước, kiểm tra trạng thái; không có kết quả thì báo thất bại và không gọi model đoán.
- `Gemma` trên máy tổng hợp với công cụ thao tác tắt, xem đoạn trích là dữ liệu không đáng tin; danh sách liên kết thật được chương trình đính kèm sau câu trả lời, không đọc URL qua loa. Nguồn là đoạn trích tìm kiếm, chưa phải đọc toàn văn/kiểm chứng; có thể cũ hoặc sai. Không lưu đoạn trích trong lịch sử hội thoại kế tiếp. Trạng thái cho thấy đang tra cứu. Thêm `web.auto_research: false` vào config nếu muốn tắt cơ chế tự tra cứu.
- Giữ lệnh “tìm ... trên Google” mở trang kết quả như trước, lệnh máy và các cách nói đã dạy giữ ưu tiên. Tính năng dùng chung router cho cửa sổ, pet và điện thoại, nhưng chưa kiểm thử mic hoặc OPPO ở đợt này. Không sửa `privacy.save_transcripts`.
- Kiểm tra: 18 bài thử mới và hồi quy đã qua (HTTP/model/hệ thống giả lập), gồm lỗi mạng, hủy, riêng tư, lệnh web/Zalo cũ. Đã thử tra cứu thật bằng câu hỏi công khai “Thủ đô của Việt Nam là gì?”: nhận bốn đoạn kết quả, Gemma cục bộ trả lời Hà Nội, kèm liên kết; hai lần thử 4,45 giây và 2,39 giây trên máy. Chưa thử câu hỏi thật qua mic.
- File: `pet/controller.py`, `pet/web_research.py`, `tests/test_web_research.py`. Nguồn/runtime đồng bộ, bản trước tại `Luu-tru/alex-online-answers-20261104`.

## Tìm kiếm Google từ lời nói hoặc nhập chữ (04/11/2026)

- Sửa lỗi “Mở [nội dung/tên lạ] trên Google” bị coi là phần mềm chưa cài. Câu nêu rõ Google/web/trình duyệt được xử lý trước phần tìm file, đoán tên app, tìm người Zalo và phát nhạc; không cần gọi model cho thao tác này.
- Từ khóa giữ nguyên dấu tiếng Việt, chữ hoa và ký tự như C++, &, được mã hóa vào URL Google. Nhận câu “Tìm ... trên Google”, “Tìm trên Google ...”, “Mở Google tìm ...”, cùng lời nhờ lịch sự. Thiếu từ khóa thì hỏi tại chỗ.
- “Mở YouTube/Portal UT trên Google” vẫn mở đúng trang đã biết. “Tìm YouTube trên Google” mở kết quả tìm kiếm. Tên lạ không tự suy ra URL và không tự nhấp kết quả đầu tiên. Tên phần mềm lạ không nêu tìm kiếm/web vẫn dùng luồng cũ.
- Lệnh phủ định, nhạc YouTube/Spotify, tìm người Zalo và câu dạy cách nói giữ luồng riêng. Không thay model, STT, giọng, khóa điện thoại hay quyền thao tác. Không bật nhật ký nội dung; tìm kiếm gửi từ khóa người dùng yêu cầu cho Google qua trình duyệt.
- File: `pet/web_search.py`, `pet/apps.py`, `pet/controller.py`; thêm `tests/test_google_search.py`. 29 bài thử mới/hồi quy đã qua với trình duyệt, model và thao tác hệ thống được giả lập; gồm router dùng chung desktop/điện thoại. Kiểm tra micro thật và OPPO chưa thực hiện ở đợt này.
- Bản trước nằm tại `Luu-tru/alex-web-search-20261104`, có hash bảo vệ khi triển khai. Đồng bộ bản source và runtime.

# Alex Desktop

## Chuyển động giao diện (04/11/2026)

- Cửa sổ Alex dùng chuyển trang mờ 210 ms và tin nhắn mới hiện nhẹ 180 ms; cập nhật từng phần trong cùng tin nhắn không chạy lại hiệu ứng. Pet trong thanh bên chạy theo tốc độ gốc tối đa 20 khung hình/giây và chỉ chạy khi hiện.
- Chuyển trang đổi trang đích ngay để giữ vòng đời camera và trạng thái nút; ảnh tạm của trang trước chỉ ở RAM trong lúc chuyển và được xóa sau hiệu ứng, khi ẩn hoặc đổi kích thước. Không lưu ảnh hội thoại.
- Hiệu ứng không thay router, mic, camera, model hay lệnh của pet. Kiểm thử giao diện gồm chuyển trang liên tiếp, kết thúc hiệu ứng, ẩn cửa sổ, cập nhật một tin nhắn, đóng ứng dụng và các nút sẵn có. Bản trước nằm tại `Luu-tru/alex-app-motion-20261104`.


Ứng dụng Windows riêng của Alex: trò chuyện bằng chữ hoặc mic, dùng các lệnh máy tính của pet, hiện/ẩn pet và kết nối điện thoại.

## Mở ứng dụng

Mở `Alex.exe` trong `D:\HỌC TẬP\dự án trợ lý ảo\Alex-Desktop`, hoặc lối tắt **Alex - Trò chuyện** trên Desktop. Có thể nhấp phải biểu tượng pet ở khay hệ thống → **Mở ứng dụng Alex**.

- Nhập câu hỏi, Enter để gửi; Shift+Enter xuống dòng.
- **Bật mic** dùng mic/nhận giọng nói hiện có của pet; nói xong Alex tự nhận câu. Mic không tự bật khi chỉ mở ứng dụng.
- **Đọc câu trả lời khi gõ** bật/tắt giọng đọc riêng cho yêu cầu nhập chữ. Mặc định không đọc.
- **Dừng** ngắt yêu cầu đang xử lý và bỏ yêu cầu còn chờ.
- **Hiện/Ẩn pet** đổi hình pet trên Desktop, không tự bật mic hoặc hủy câu đang trả lời.
- **Trò chuyện mới** xóa ngữ cảnh hội thoại đang giữ trong bộ nhớ của bộ xử lý dùng chung. Cách nói/ứng dụng đã dạy vẫn giữ.
- Đóng cửa sổ Alex chỉ ẩn cửa sổ; pet và kết nối điện thoại vẫn chạy. Muốn thoát toàn bộ: menu khay → **Thoát Alex**.

## Bộ xử lý dùng chung

Đây là ứng dụng Alex sẵn có, dùng chung Python, Whisper, giọng Thái Sơn và router lệnh với pet. Hội thoại được xử lý bằng model Gemma cục bộ trong `Alex-data`; ứng dụng Bionic đã được gỡ và không cần Gemini API cho chế độ này. Chi tiết cấu hình và đường dẫn có trong `GEMMA-LOCAL.md`.

Chạy nhiều lần lối tắt chỉ đưa cửa sổ Alex đang chạy lên trước, không nạp thêm model/mic. Cửa sổ được viết bằng Qt Widgets, không tạo trình duyệt/WebEngine thứ hai.

## Lệnh máy tính

Các câu nhập chữ đi vào cùng router với pet: mở ứng dụng/web/thư mục, âm lượng/độ sáng và các lệnh đã có. Nếu không có đích rõ hoặc chưa xác nhận kết quả, Alex báo lại thay vì khẳng định đã làm.

Với “cửa sổ hiện tại”/“đóng tab”, khi gõ trong Alex, đích là cửa sổ khác bạn vừa dùng trước khi trở lại Alex. Bộ xử lý kiểm tra lại đúng cửa sổ và đưa nó lên trước; nếu cửa sổ đã mất/đổi hoặc Windows từ chối thì không thao tác. Không gửi phím đóng vào chính Alex.

## Riêng tư

Hội thoại của cửa sổ giữ trong RAM trong phiên; không tự lưu lịch sử chat ra file, không thay `privacy.save_transcripts=false`. Nội dung model được hiển thị dạng chữ, không tải ảnh hoặc chạy HTML do model trả về. Kênh mở cửa sổ chỉ cho cùng tài khoản Windows và chỉ nhận lệnh `show`, không nhận câu chat/lệnh hệ thống.

## Các file chính

Trong repo `trợ lý ảo-local\source\alex-assistant\desktop`:

- `pet/app_window.py`: giao diện, composer, hiển thị streaming, các nút pet/mic.
- `pet/desktop_requests.py`: hàng đợi một lượt, router dùng chung, chống phát lại yêu cầu cũ sau Sleep, lựa chọn giọng đọc.
- `pet/app_ipc.py`: kênh đưa cửa sổ sẵn có lên trước.
- `pet/controller.py`: tích hợp lượt nhập chữ vào worker hiện có.
- `pet/window.py`: mục menu mở ứng dụng Alex.
- `main.py`, `launch.py`: cờ `--app` và vòng đời ứng dụng.
- `tools/AlexDesktopLauncher.cs`: launcher Windows nhỏ, dùng runtime đã cài trong dự án.

Launcher dùng đường dẫn tương đối trong thư mục dự án. Không tách `Alex-Desktop` khỏi `trợ lý ảo-local` nếu chưa cập nhật launcher. Không cần cài thêm model hoặc sao chép profile Bionic.

## Kiểm tra tìm kiếm thực tế (04/11/2026)

- Đã nhập câu thử không riêng tư trong Alex: “Mở cách làm bánh flan trên Google”. Router nhận yêu cầu web, trình duyệt mở trang kết quả Google đúng từ khóa có dấu. Chưa thử giọng nói thật hay trên điện thoại.

## Kiểm tra tra cứu trong cửa sổ Alex (04/11/2026)

- Đã khởi động lại Alex và nhập câu hỏi công khai “Thủ đô của Việt Nam là gì?”. Cửa sổ hiển thị câu trả lời Hà Nội cùng liên kết nguồn; hoàn tất trong 3,0 giây. Chưa kiểm tra giọng nói thật hoặc điện thoại.

## Điều chỉnh bố cục Vũ trụ (04/11/2026)

- Kiểm tra cửa sổ Windows thật thấy ảnh hành tinh chồng lên thông tin ở khung bên phải. Đã cho ảnh co theo không gian, làm rõ nút +/- và bổ sung kiểm tra không chồng lấn ở 800×580, 1122×810 và 1280×860.

## Cử chỉ Vũ trụ và bóc tách (04/11/2026)

- Camera chỉ bật khi người dùng chọn. Chụm cái và trỏ một tay rồi di chuyển để xoay; mở hai tay đưa ra/khép vào để zoom; chụm cả hai tay rồi kéo ra để mở và tách các lớp, khép vào để ghép. Khi mất tay hoặc đổi cử chỉ không nhảy góc.
- Góc nhìn quỹ đạo cho phép xoay tròn cả hai trục. Ở chế độ các lớp, xoay bề mặt hành tinh theo chiều ngang; các đĩa lớp là minh họa 2D, không phải vật thể 3D đầy đủ.
- 36 kiểm tra tự động thông qua với dữ liệu tay mô phỏng, chưa xác nhận với camera thực.

## Sửa cử chỉ ghép hành tinh (04/11/2026)

- Khép hai bàn tay đang chụm làm mức tách giảm; khi gần 0, tự chạy chuyển cảnh ghép và quay về hệ Mặt Trời. Độ nhạy khép cao hơn để phù hợp khung hình camera. Không mở lại khi tay đang rung; nhả cử chỉ trước khi mở lại.
- Đã chạy 37 kiểm tra tự động; cần người dùng kiểm tra camera thực.

## Bóc tách bằng vỏ cầu (04/11/2026)

- Thay các đĩa phẳng bằng hình cầu nguyên vẹn chuyển dần thành các vỏ cầu cắt mở lồng nhau và lõi hình cầu. Mỗi lớp có số, nhãn chọn được, màu và đổ bóng; hình minh họa bằng phép vẽ 2D, không phải mô hình 3D hay tỷ lệ thực.
- Giữ nguyên cử chỉ hai tay, zoom, kéo, ghép và vòng đời camera; đã kiểm tra tự động 38 bài và ảnh xem trước trên Windows.

## Bóc tách lớp cầu theo các hướng (04/11/2026)

- Theo ý người dùng, hành tinh nguyên vẹn chuyển thành các quả cầu biểu diễn từng lớp bung về các hướng quanh tâm (4 lớp: 4 hướng; 3 lớp: 3 hướng), thay vì chuỗi vỏ khuyết. Chọn quả cầu hoặc nhãn để xem lớp; cử chỉ hai tay và chế độ ghép vẫn giữ. Đây là minh họa 2D có đổ bóng, không phải mô hình 3D hay tỉ lệ thực.
- Đã qua 39 kiểm tra tự động, gồm bố cục 3/4 lớp, chọn quả cầu, zoom, cử chỉ và vòng đời camera.

## Tách một hành tinh thành bốn mảnh (04/11/2026)

- Người dùng làm rõ: bốn mảnh là các phần của cùng một quả hành tinh ghép khít, không phải bốn quả cầu độc lập. Hiệu ứng mới chia bề mặt cùng hình thành bốn góc, di chuyển theo bốn hướng và hiện mặt cắt các lớp bên trong khi mở; ghép lại khôi phục bề mặt nguyên. Phần màu là minh họa, không theo tỷ lệ thực.
- Giữ cử chỉ hai tay, zoom và lựa chọn tên lớp; 39 kiểm tra tự động đạt.

## Bóc tách tuần tự theo điểm, hiệu ứng vỡ (04/11/2026)

- Người dùng làm rõ: cử chỉ tiếp tục kéo qua điểm 1, 2, 3, 4 thì từng lớp tương ứng lần lượt nứt và vỡ như thủy tinh, lộ lớp kế; khép tay để ghép lại. Trái Đất có 4 điểm: vỏ, lớp phủ, lõi ngoài, lõi trong; hành tinh khác dùng số lớp hiện có. Các mảnh và màu là hình minh họa 2D, không theo tỷ lệ hay vật lý thực.
- Thanh mức tách hiển thị điểm hiện tại; không thay đổi luồng camera/cử chỉ. Đã qua 41 bài kiểm tra tự động, bao gồm cử chỉ giả lập qua đủ 4 điểm và ghép lại.

## Hiệu ứng nứt kính, mảnh nhỏ bay ra (04/11/2026)

- Người dùng chọn: từng lớp lần lượt hiện đường nứt giống kính, sau đó chia thành nhiều mảnh không đều bay ra; giữ cơ chế 4 điểm và ghép ngược. Đây là hình minh họa, không mô phỏng vật lý thực.
- Có bộ nhớ đệm giới hạn 3 lớp đã vỡ nhằm giảm tải, xóa khi đổi hành tinh; đã chạy 42 bài kiểm tra tự động, bao gồm thứ tự 4 điểm và kích thước bộ nhớ đệm.

## Cử chỉ bóc tách chậm và mượt hơn (04/11/2026)

- Giảm độ nhạy tách/ghép, cộng dồn mục tiêu không làm tròn và nội suy 180 ms giữa các mẫu camera để các mảnh không giật. Có thể nhả tay rồi chụm lại kéo tiếp. Kéo thanh trượt, chuyển hành tinh, tắt camera hoặc rời trang hủy nội suy đang chờ.
- Đã qua 44 kiểm tra tự động, bao gồm đi đủ bốn điểm, ghép, nhả tay, thanh trượt, rời trang và vòng đời camera; cần xác nhận lại bằng tay thật.

## Vũ trụ sắc nét hơn, ảnh Trái Đất NASA (04/11/2026)

- Đã thêm ảnh bề mặt Blue Marble 2048×1024 của NASA vào assets/space, chạy ngoại tuyến; mây phủ là mô phỏng và có dự phòng nếu thiếu ảnh. Ghi nguồn và tín dụng trong assets/space/NGUON-ANH.md. Các hành tinh khác vẫn là minh họa bằng mã; đây không phải bộ ảnh 4K thực cho mọi hành tinh.
- Cảnh sao thêm lớp sáng; ảnh cận cảnh tự tăng độ phân giải theo zoom/DPI, giới hạn 1536px và cache có giới hạn. Mảnh vỡ đã hoàn tất được cache theo vùng nhỏ và mức zoom, tránh cấp phát theo cả màn hình. Nhãn lớp cố định khi zoom/kéo và vẫn chọn được. Giữ cử chỉ, camera và bốn điểm như trước.
- 48 kiểm tra tự động đạt; ảnh xem trước và kiểm tra tốc độ tổng hợp trên Windows.

## Vũ trụ: tám hành tinh và cấu tạo riêng (04/11/2026)

- Bổ sung bảy bản đồ 2K Solar System Scope / INOVE (CC BY 4.0) cho các hành tinh còn lại; Trái Đất tiếp tục dùng ảnh NASA. Bản đồ dùng ngoại tuyến, có dự phòng và ghi nguồn trong assets/space/NGUON-ANH.md. Sao Kim hiển thị mây; các hành tinh khí/băng không có bề mặt rắn.
- Sửa chú thích và các lớp theo từng hành tinh, bổ sung khí quyển Sao Kim, tách mô hình Sao Mộc/Sao Thổ và Thiên Vương/Hải Vương; ghi rõ nội thất chưa chắc chắn. Mô hình vỡ là minh họa, không theo tỉ lệ; khí và chất lưu không vỡ như kính. Mô tả tự theo lớp đang tách/ghép và có thể chọn từng lớp.
- Cache giới hạn 10 ảnh, dùng mức 1024×512 khi nhìn xa và 2048×1024 khi cận; giữ camera chỉ bật khi người dùng chọn. Đã kiểm tra 48 bài tự động.

## Vũ trụ: hình cắt lớp hành tinh (04/11/2026)

- Mặc định hiển thị hành tinh cắt mở dần, các lớp bên trong theo từng thiên thể; giữ điều khiển chụm hai tay để mở/đóng. Độ dày lớp mỏng được phóng đại, các ranh giới bên trong là mô hình minh họa, đặc biệt các hành tinh khổng lồ.
- Giữ hiệu ứng mảnh kính cũ dưới ô “Hiệu ứng kính” trong chế độ bóc tách. Sao Hải Vương được giảm bớt độ xanh đậm; xem nguồn ảnh và lý do trong assets/space/NGUON-ANH.md. Camera vẫn chỉ mở khi người dùng chọn.
- Đã kiểm tra 49 bài tự động, gồm chuyển 8 hành tinh, hai kiểu hiển thị, cử chỉ và hoạt động tắt/mở camera.

## Vũ trụ: giữ lõi và bổ sung chất liệu (04/11/2026)

- Vùng lõi không bị vỡ trong cả chế độ cắt lớp và hiệu ứng kính, bao gồm lõi trong và lõi ngoài Trái Đất; các lớp bên ngoài vẫn có hiệu ứng cũ.
- Các lớp có chất liệu đá, khí và chất lưu minh họa riêng, đổ sáng và chi tiết hơn; phóng lớn hình trong khu vực bóc tách. Đây là hình tạo bằng thuật toán, không phải ảnh thực tế của cấu trúc bên trong. Giới hạn bộ nhớ đệm 8 ảnh, xóa cache khi rời trang. Nguồn khoa học ghi trong assets/space/NGUON-ANH.md.
- Chụm hai tay điều khiển tách/ghép như trước; camera chỉ bật khi chọn. Kiểm tra tự động toàn bộ tám hành tinh ở các giai đoạn và cả hai kiểu xem.

## Điều chỉnh theo yêu cầu: chỉ lớp trong cùng không vỡ (04/11/2026)

- Thay hướng dẫn ở mục trước: chỉ lớp trong cùng của mỗi hành tinh giữ nguyên. Các lớp trước nó, gồm lõi ngoài của Trái Đất, có thể tách/vỡ bằng hiệu ứng nghệ thuật. Lõi ngoài Trái Đất là chất lỏng nên hiệu ứng vỡ không biểu diễn vật lý thật.
- Dùng bán kính tương đối riêng cho từng lớp trong cả hai chế độ; lớp mỏng vẫn phóng đại và cấu trúc các hành tinh khổng lồ còn chưa chắc chắn. Hiệu ứng vỡ là mặc định; có thể bỏ chọn để xem hình cắt lớp, không ảnh hưởng cử chỉ. Màu và chất liệu bên trong được tạo để minh họa; ranh giới khí được làm mềm. Nguồn xem assets/space/NGUON-ANH.md.
- Đã kiểm tra tự động 8 hành tinh, lớp trong cùng luôn nguyên và lõi ngoài Trái Đất có thể tách; giữ camera chỉ bật khi người dùng chọn.

## Vũ trụ: chuyển cử chỉ mượt và toàn màn hình (04/11/2026)

- Một tay chụm điều khiển xoay và giữ nguyên zoom ngay cả khi tay còn lại vẫn trong khung; hai tay mở zoom, hai tay chụm tách/ghép. Khi đổi chế độ hoặc mất tay thì hủy chuyển động còn chờ, không tiếp tục zoom/di chuyển do đà. Lọc rung, giới hạn bước zoom, và tạm giữ zoom nếu bàn tay gần mép camera. Nội suy chuyển động giữa các khung; camera vật lý vẫn có giới hạn góc nhìn.
- Nút Toàn màn hình trong trang Vũ trụ ẩn thanh bên, mở rộng cửa sổ Alex; Esc hoặc nút Thoát toàn màn hình quay lại trạng thái cửa sổ trước đó. Rời trang và đóng cửa sổ cũng khôi phục chế độ cũ. Không tự bật camera.
- Đã kiểm tra tự động chuyển hai tay mở sang một tay chụm, mất tay, đổi sang bóc tách, vào/thoát toàn màn hình và khôi phục cửa sổ phóng đại.

## Vũ trụ: khung mô phỏng phủ toàn màn hình (04/11/2026)

- Điều chỉnh yêu cầu toàn màn hình: riêng vùng mô phỏng hệ Mặt Trời hoặc vùng bóc tách chiếm toàn màn hình; ẩn bảng thông tin, thanh bên và các điều khiển thường. Thanh nổi nhỏ có bật/tắt camera, bóc tách/ghép và thoát; Esc cũng thoát. Không tự bật hoặc tắt camera khi đổi chế độ.
- Giữ trạng thái zoom, góc nhìn, hành tinh và lớp hiện tại khi chuyển; trả lại điều khiển bình thường và trạng thái cửa sổ trước khi thoát. Không gọi _planet khi resize để tránh reset việc tách lớp.
- Đã kiểm tra diện tích khung bằng cửa sổ, nút nổi, camera, vào/thoát, trạng thái cửa sổ phóng đại, và các chức năng Vũ trụ sẵn có.

- Bổ sung: nếu pet đang hiện khi mở khung Vũ trụ toàn màn hình, tạm ẩn pet để không che mô phỏng và hiện lại khi thoát; không thay đổi trạng thái mic.

## Vũ trụ: chạm ngón tay hai lần để đổi toàn màn hình (04/11/2026)

- Khi camera do người dùng bật và chỉ thấy một bàn tay, chạm ngón cái và ngón trỏ, thả ra, chạm lần hai liên tiếp để bật hoặc thoát toàn màn hình. Có giới hạn thời gian và khoảng di chuyển, cần thả tay và có thời gian chống lặp; giữ chụm xoay và thao tác hai tay không kích hoạt.
- Cử chỉ chỉ đổi chế độ Vũ trụ, không tự bật camera; giữ nguyên zoom và thao tác tách/ghép. Có hướng dẫn trên trang và nút/Esc vẫn dùng được. Đã kiểm tra mô phỏng chuỗi tay hợp lệ, giữ tay, di chuyển, hai tay, lặp và vào/thoát toàn màn hình; cần người dùng thử camera thực tế.

## Sửa cử chỉ chạm hai lần không được nhận (04/11/2026)

- Camera người dùng đang bật. Lý do cụ thể chưa có dữ liệu; bộ nhận cũ đòi đúng một tay và chuỗi chạm dưới 0,95 giây. Bản mới cho phép một tay chạm khi tay kia đang mở, dùng vị trí bàn tay để theo dõi cùng một tay, chịu mất dấu ngắn và nới thời gian chuỗi chạm. Hai tay cùng chụm vẫn dành cho bóc tách; thao tác giữ để xoay không tự toàn màn hình.
- Thêm phản hồi “Đã chạm 1” ở trạng thái camera và thanh nổi toàn màn hình. Không lưu ảnh, tọa độ hay nội dung từ camera. Cần người dùng kiểm tra lại trực tiếp sau khi mở lại Alex.

## Vũ trụ: dấu V để bật hoặc thoát toàn màn hình (04/11/2026)

- Theo lựa chọn của người dùng, thay cử chỉ chạm cái–trỏ hai lần bằng dấu V (trỏ và giữa duỗi, hai ngón còn lại gập) giữ khoảng 1,1 giây. Chụm cái–trỏ vẫn dùng để xoay; hai tay mở để zoom, hai tay chụm tách/ghép. Chạm hai lần không còn đổi toàn màn hình.
- Hiện tiến trình giữ dấu V; khóa lặp khi vẫn giữ, cần hạ tay hoặc đổi tư thế một lúc trước khi kích hoạt lại. Cho phép một tay thứ hai thả lỏng nhưng không khi tay kia chụm; xử lý mất dấu ngắn. Không tự bật camera, không lưu hình hay tọa độ tay.
- Kiểm tra tự động thời gian giữ, hạ tay, tránh lặp, đổi kích thước và góc tay, mất dấu, giữ zoom, hai tay và cử chỉ cũ. Cần thử thực tế với bàn tay và camera của người dùng.

## Gemma: trả lời tự nhiên theo tính cách Alex (04/11/2026)

- Nguyên nhân: _compact_chat_payload thay system prompt bằng bản ngắn chỉ ghi “vui vẻ, tự nhiên”, làm mất hướng dẫn vui tính/hài hước của Alex. Cập nhật prompt ngắn để phản hồi vui khi phù hợp, đồng cảm khi cần, không tự nhận đã thao tác, xưng mình/gọi bạn; không thay luồng gọi công cụ.
- Giữ tối đa ba lượt hội thoại gần nhất trong ngân sách 1500 ký tự; không thay cấu hình model, mic, lưu bản ghi hay quyền riêng tư. Gemma vẫn chạy tại địa chỉ loopback của laptop.
- Phát hiện source/pet/llm.py khác runtime và thiếu hàm tìm backend; Gemma có phương án tìm backend cục bộ dự phòng cho source cũ mà không ghi đè llm.py. Có bài kiểm tra prompt, tool payload và fallback. Thử trực tiếp bằng câu hỏi mẫu không chứa dữ liệu người dùng.

## Tra cứu kiến thức và chờ khi nói (04/11/2026)

- Bổ sung nhận diện câu hỏi lịch sử, địa lý và chủ quyền như “thuộc nước nào”, “bạn có biết quần đảo...”; vẫn loại trừ nội dung riêng tư và lệnh máy.
- Với câu hỏi về Hoàng Sa hoặc Trường Sa, tìm thêm trích đoạn từ Bộ Ngoại giao Việt Nam bên cạnh kết quả chung; dữ liệu vẫn là trích đoạn chưa kiểm chứng. Hướng dẫn Gemma phân biệt lập trường, thực tế kiểm soát và kết luận pháp lý.
- Tăng audio.silence_ms từ 840 lên 1500 để giảm ngắt khi ngập ngừng; có thêm độ trễ 0,66 giây khi kết thúc câu. Không thay đổi lưu nhật ký riêng tư.
- Kiểm tra định tuyến, riêng tư và ngắt câu mô phỏng; thử câu hỏi mẫu công khai qua mạng và Gemma cục bộ. Cần người dùng thử mic thật sau khi mở lại Alex.

## Sửa lỗi nguồn tìm kiếm trả trang kiểm tra (04/11/2026)

- DuckDuckGo HTML trả HTTP 202 thay cho kết quả ở một số câu hỏi; thêm thử phiên bản Lite và đọc kết quả/trích đoạn tương ứng. Với câu hỏi chủ quyền Hoàng Sa, Trường Sa, khi câu dài bị chặn, thử lại bằng từ khóa công khai ngắn giới hạn nguồn Bộ Ngoại giao.
- Không thay chính sách nội dung riêng tư hay bật lưu hội thoại. Nếu cả hai đường tìm kiếm thất bại, vẫn báo không lấy được nguồn, không khẳng định đã tra cứu. Kiểm tra bằng câu hỏi mẫu và thử lại với pet.

## Chỉ hiện câu trả lời tra cứu (04/11/2026)

- Theo yêu cầu người dùng, Alex không tự đính kèm danh sách nguồn trong chat; vẫn tra cứu và dùng trích đoạn để tổng hợp. Bộ lọc luồng loại ký hiệu trích dẫn số và mục nguồn model tự sinh khỏi văn bản lẫn giọng nói.
- Giữ báo lỗi khi không lấy được kết quả, không thay chính sách bảo mật. Đã kiểm tra luồng desktop/điện thoại, dấu trích dẫn tách qua nhiều chunk và câu bình thường bắt đầu bằng “Nguồn gốc”.

## Giữ âm đầu câu và tránh sửa nhầm (04/11/2026)

- Runtime trước đó cắt âm đầu theo ngưỡng RMS, có thể bỏ âm tiết nói nhỏ trong phần đệm VAD. Giữ nguyên toàn bộ đầu đoạn thu, chỉ cắt đuôi yên lặng. Source vốn giữ đầu đoạn, nên không đồng bộ đè các khác biệt khác.
- Không chuyển câu bắt đầu “bởi vì” thành lệnh mở; giữ các ngưỡng chống ảo giác và thiết lập riêng tư, không lưu âm thanh hay lời nói. Có kiểm tra âm đầu yếu mô phỏng và sửa tiền tố. Cần người dùng thử giọng thật vì chưa có ví dụ cụ thể; chưa khẳng định mức chính xác ngoài thực tế.
