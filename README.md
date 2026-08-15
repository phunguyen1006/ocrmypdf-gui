# OCRmyPDF GUI

Ứng dụng desktop Windows tối giản cho OCRmyPDF. Kéo PDF scan vào ứng dụng,
chọn ngôn ngữ và nhận một PDF có thể tìm kiếm, chọn và sao chép văn bản.

## Tính năng

- Kéo thả một hoặc nhiều PDF; kéo cả thư mục để thêm các PDF bên trong.
- Queue theo từng file, không chạy OCR trên GUI thread.
- OCR chạy trong process riêng, có progress theo stage, ETA, log và Cancel.
- Ngôn ngữ tiếng Việt, tiếng Anh, toàn bộ catalogue Tesseract và lựa chọn custom.
- Auto detect ngôn ngữ thích ứng: mọi trang với PDF ngắn, các trang đại diện với PDF dài; lazy-download model và cache trong app data.
- Preset Quick, Standard và Difficult Scan.
- OCR mode Skip, Redo và Force.
- Chọn page range, loại trừ trang, sidecar TXT, PDF/PDF-A và tối ưu PDF.
- Không sửa file input, không ghi đè output im lặng; output mặc định là
  `input (OCR).pdf`, sau đó `input (OCR 2).pdf`, `input (OCR 3).pdf`...
- Lịch sử xử lý lưu bằng SQLite và settings lưu bằng QSettings.
- Giao diện monochrome: trắng, đen và grayscale; màu đỏ chỉ dùng cho lỗi nguy hiểm.

## Yêu cầu

- Windows 10/11 64-bit.
- Python 3.10 trở lên; dự án đã được kiểm tra với Python 3.14.
- OCRmyPDF 17.x, PySide6, pikepdf, Pillow, pypdfium2 và Lingua.
- Tesseract OCR 5.x. Cài language data tương ứng, tối thiểu `eng` và `vie`.
- Ghostscript cho một số pipeline PDF/A/optimization.

V1 không bundle Tesseract hoặc Ghostscript. Ứng dụng tự kiểm tra component khi
khởi động và hiển thị hướng dẫn nếu thiếu.

## Cài dependency

Mở PowerShell tại thư mục project:

```powershell
python -m pip install -r requirements.txt
```

Cài Tesseract từ [UB Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
và chọn language data `English` + `Vietnamese` trong installer. Kiểm tra:

```powershell
tesseract --version
tesseract --list-langs
```

Cài Ghostscript từ [Ghostscript releases](https://ghostscript.com/releases/gsdnld.html)
nếu cần PDF/A hoặc pipeline yêu cầu rasterizer này.

## Chạy ứng dụng từ source

```powershell
python -m app.main
```

Worker được gọi nội bộ bằng `python -m app.main --worker`; người dùng bình thường
không cần mở terminal.

## Sử dụng nhanh

1. Mở app.
2. Kéo PDF vào vùng drop hoặc bấm `Choose PDF files`.
3. Chọn `Vietnamese + English` nếu hai language pack đã cài.
4. Chọn `Standard`, bật `Auto rotate` và `Fix tilted pages` khi cần.
5. Bấm `Start OCR`.
6. Bấm `Open PDF` khi job hoàn thành.

Các thiết lập ít dùng nằm trong `Advanced settings`. Nếu một job lỗi, row trong
queue vẫn giữ nguyên nguyên nhân và có action `Retry`, `Log` hoặc `Remove`.

## Test

Unit tests:

```powershell
python -m pytest -q tests/test_page_ranges.py tests/test_output_paths.py tests/test_settings.py tests/test_jobs.py tests/test_ocr_options.py tests/test_dependencies.py
```

Integration/GUI smoke tests cần Tesseract và dùng Qt offscreen:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:OCRMY_PDF_GUI_DATA_DIR = "$PWD/.test-appdata"
python -m pytest -q tests/test_gui_smoke.py
```

`OCRMY_PDF_GUI_DATA_DIR` là biến tùy chọn để đặt history/log/temp vào thư mục
đã chọn. Khi không đặt, app dùng `%LOCALAPPDATA%\OCRmyPDF-GUI`.

## Build Windows onedir

Bản build đầu tiên dùng `onedir` để khởi động nhanh và dễ kiểm tra dependency:

```powershell
.\scripts\build_windows.ps1
```

Kết quả nằm trong `dist\OCRmyPDF-GUI\OCRmyPDF-GUI.exe`. Tesseract và
Ghostscript vẫn là dependency bên ngoài theo chiến lược V1.

Nếu bản build cũ đang mở và Windows khóa thư mục `dist`, có thể build sang thư
mục khác:

```powershell
.\scripts\build_windows.ps1 -DistPath .\dist-new -WorkPath .\build-new
```

## PDF nhiều ngôn ngữ và lỗi thường gặp

Trong `Custom...`, chọn tất cả language có thể xuất hiện trong tài liệu, ví dụ
`vie` + `chi_sim` cho giáo trình Việt–Trung. Tesseract sẽ nhận diện văn bản
trong cùng một lần OCR; không cần tách PDF theo ngôn ngữ. Các file PDF nằm trên
ổ cloud/ổ mạng nên được đồng bộ hoàn toàn hoặc chép tạm về ổ local trước khi
OCR, vì OCRmyPDF phải tạo nhiều file tạm và đọc lại từng trang.

Worker và các tiến trình Tesseract/Ghostscript chạy ẩn, không mở cửa sổ CMD.
Nếu job lỗi, bấm `Log` ở dòng file để xem chẩn đoán chi tiết thay vì chỉ xem
mã thoát tổng quát.

## Kiến trúc

```text
PySide6 GUI
  └─ QueueManager / QProcess / JSON lines IPC
       └─ ocr_worker.py (process riêng)
            └─ OCRmyPDF Python API + EventProgressBar plugin
                 ├─ Tesseract
                 └─ PDF backend / Ghostscript
```

Worker luôn ghi output vào thư mục tạm của job trước. Chỉ khi OCR thành công,
file mới được publish sang output cuối cùng. Thư mục tạm được dọn khi thành công,
lỗi hoặc hủy; các thư mục cũ hơn một giờ được dọn khi worker khởi động lại.

## Giới hạn MVP

- `Pause Queue` chỉ ngăn job tiếp theo bắt đầu; không pause/resume giữa một PDF.
- Mỗi lần mặc định xử lý một PDF. Có thể tăng `Concurrent files`, nhưng sẽ dùng
  thêm RAM/CPU và không được khuyến nghị cho máy yếu.
- Tesseract/Ghostscript chưa được đóng gói vào installer; app chỉ detect và hướng dẫn.
- OCRmyPDF có thể bỏ qua một page vượt `Maximum OCR time per page`; nội dung gốc
  của page đó vẫn được giữ trong output nhưng page sẽ không có OCR text tương ứng.

## Language catalogue, lazy download and Auto detect

The language picker ships with a local snapshot of the official
[`tessdata_fast`](https://github.com/tesseract-ocr/tessdata_fast) catalogue pinned
to commit `87416418657359cb625c412a48b6e1d6d41c29bd` (126 language models and 37
script models). Opening the picker never calls the network. Search by name or
code and filter by `All`, `Installed`, `Cached`, or `Available`.

Missing language packs are downloaded only when OCR needs them, over HTTPS from
the pinned official source. Files are written to a user-scoped cache at
`%LOCALAPPDATA%\OCRmyPDF-GUI\tessdata`, first as `.part`, then verified with
size and Git blob SHA-1 before an atomic rename. The app never writes to
`C:\Program Files\Tesseract-OCR` and does not require Administrator access.

Choose `Auto detect — adaptive pages` for a multilingual PDF. Detection runs
locally with pypdfium2, Tesseract script probing, and the offline Lingua
detector; PDF contents are never uploaded. Short PDFs are checked page by page,
while long textbooks use evenly distributed representative pages so the queue
does not remain at `Waiting` for minutes. Results are cached per file/page. A
confident result silently prepares missing models. Ambiguous results show a
candidate dialog so the user can confirm the languages before OCR begins.

The Advanced Settings window is resizable, vertically scrollable on small
screens, and keeps its OK/Cancel footer visible. OCR workers, language probes,
and downloads use hidden Windows subprocesses, so OCR does not flash CMD
windows.
