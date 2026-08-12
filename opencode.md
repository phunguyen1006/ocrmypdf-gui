# PROMPT CHO CODEX — XÂY DỰNG OCRmyPDF GUI

## 1. Mục tiêu dự án

Hãy xây dựng một ứng dụng desktop Windows hoàn chỉnh có giao diện đồ họa cho **OCRmyPDF**, giúp người dùng biến PDF scan dạng ảnh thành PDF có thể:

- select text;
- copy/paste;
- Ctrl+F;
- search;
- giữ hình ảnh và bố cục PDF gốc;
- OCR tiếng Việt, tiếng Anh và nhiều ngôn ngữ khác.

Tên project/repository tạm thời:

```text
ocrmypdf-gui
```

Tên app hiển thị:

```text
OCRmyPDF GUI
```

Đây phải là một **ứng dụng Windows thực sự có thể dùng hàng ngày**, không phải demo UI.

Ưu tiên:

```text
Dễ dùng
Ổn định
Không treo GUI
Hiển thị tiến trình rõ ràng
Xử lý lỗi tốt
Batch processing
Không bắt người dùng phải nhớ command line
```

---

# 2. Tech stack

Sử dụng:

```text
Python 3.14
PySide6
OCRmyPDF
Tesseract OCR
pikepdf
PyInstaller
```

Có thể thêm dependency nhỏ nếu thực sự cần.

Không sử dụng Electron.

Không viết lại OCR engine.

OCRmyPDF phải là backend OCR chính.

### Architecture

Thiết kế theo cấu trúc:

```text
┌──────────────────────────────┐
│          PySide6 GUI         │
│                              │
│ File Queue                   │
│ OCR Settings                 │
│ Progress                     │
│ Logs                         │
└──────────────┬───────────────┘
               │
               │ IPC
               ▼
┌──────────────────────────────┐
│         OCR Worker           │
│                              │
│ OCRmyPDF Python API          │
│ OcrOptions                   │
│ Progress Reporter            │
└──────────────┬───────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
   Tesseract       PDF backend
```

**Không chạy OCR trực tiếp trên GUI thread.**

OCR phải chạy trong process riêng.

Nếu OCR worker crash thì GUI không được crash theo.

OCRmyPDF hiện có API Python chính thức và tài liệu cũng đề xuất child process cho ứng dụng tích hợp.

---

# GIAI ĐOẠN 1 — CORE OCR ENGINE + DEPENDENCY DETECTION

Đầu tiên chưa cần làm UI quá đẹp. Làm backend thật chắc trước.

## 1.1. Dependency checker

Khi app mở lần đầu, tự kiểm tra:

```text
Python runtime
OCRmyPDF
Tesseract
Ghostscript nếu pipeline cần
Tesseract tessdata
```

Kiểm tra version của:

```text
OCRmyPDF
Tesseract
Ghostscript
```

Hiển thị trạng thái:

```text
✓ OCRmyPDF 17.x
✓ Tesseract 5.x
✓ Ghostscript 10.x
✓ English language
✓ Vietnamese language
```

hoặc:

```text
✕ Vietnamese language data missing
```

Không được chỉ hiện:

```text
Process exited with code 3
```

mà phải chuyển thành lỗi dễ hiểu.

Ví dụ:

```text
Vietnamese OCR is not installed.

Missing Tesseract language:
vie

Install Vietnamese language data to use this option.
```

---

## 1.2. Detect Tesseract language packs

Chạy hoặc lấy thông tin tương đương:

```text
tesseract --list-langs
```

Parse thành danh sách.

Ví dụ:

```text
eng
vie
chi_sim
chi_tra
jpn
kor
fra
deu
...
```

GUI chỉ cho phép chọn language đã cài.

Các lựa chọn mặc định:

```text
Vietnamese
English
Vietnamese + English
```

Map:

```text
Vietnamese          → vie
English             → eng
Vietnamese + English → vie+eng
```

Sau này cho phép chọn nhiều language.

OCRmyPDF hỗ trợ nhiều ngôn ngữ kết hợp như `eng+fra`, nhưng language data tương ứng phải có trong OCR engine.

---

## 1.3. OCR Worker

Tạo riêng:

```text
ocr_worker.py
```

Worker nhận một JSON job.

Ví dụ logic:

```json
{
  "input": "...",
  "output": "...",
  "languages": ["vie", "eng"],
  "deskew": true,
  "rotate_pages": true,
  "pages": null,
  "timeout": 180,
  "mode": "skip"
}
```

Sau đó chuyển thành `OcrOptions`.

Ưu tiên dùng:

```python
from ocrmypdf import OcrOptions
```

thay vì ghép một command string khổng lồ.

---

## 1.4. IPC / Event system

Worker gửi event về GUI theo dạng có cấu trúc.

Ví dụ:

```json
{"type":"started"}
```

```json
{
  "type":"progress",
  "current":51,
  "total":382,
  "stage":"OCR"
}
```

```json
{
  "type":"warning",
  "page":51,
  "message":"Tesseract timeout"
}
```

```json
{
  "type":"completed",
  "output":"..."
}
```

```json
{
  "type":"failed",
  "message":"..."
}
```

Không phụ thuộc hoàn toàn vào regex đọc progress bar terminal nếu có thể tránh.

Nghiên cứu custom `ProgressBar` plugin của OCRmyPDF để lấy progress một cách sạch.

---

# GIAI ĐOẠN 2 — GUI CHÍNH

Thiết kế giao diện như một desktop utility hiện đại, tối giản.

Không nhồi quá nhiều setting lên màn hình chính.

## 2.1. Main window

Layout:

```text
┌───────────────────────────────────────────────────────────┐
│ OCRmyPDF GUI                                    ⚙ Settings │
├───────────────────────────────────────────────────────────┤
│                                                           │
│              Drop PDF files here                          │
│                                                           │
│                 or                                        │
│                                                           │
│              [ Choose Files ]                             │
│                                                           │
├───────────────────────────────────────────────────────────┤
│ Files                                                     │
│                                                           │
│ textbook.pdf                         Ready                 │
│ document.pdf                         Ready                 │
│ scan.pdf                             Ready                 │
│                                                           │
├───────────────────────────────────────────────────────────┤
│ OCR Language                                              │
│ [ Vietnamese + English ▼ ]                                │
│                                                           │
│ Preset                                                    │
│ [ Standard ▼ ]                                            │
│                                                           │
│ ☑ Auto rotate                                             │
│ ☑ Fix tilted pages                                        │
│                                                           │
│                               [ Start OCR ]                │
└───────────────────────────────────────────────────────────┘
```

---

# 2.2. Drag & Drop

Phải hỗ trợ:

```text
1 PDF
nhiều PDF
folder
```

Khi kéo folder vào:

- tìm tất cả `.pdf`;
- hỏi có thêm toàn bộ vào queue không.

Không cho duplicate job nếu cùng input + output.

---

# 2.3. File Queue

Mỗi file là một job.

Các trạng thái:

```text
Waiting
Processing
Completed
Failed
Cancelled
Skipped
```

Mỗi row hiển thị:

```text
filename
pages
size
status
progress
output location
```

Ví dụ:

```text
Giáo trình.pdf

382 pages
84.2 MB

OCR 51 / 382
13%
```

---

# 2.4. Output naming

Mặc định:

```text
input.pdf
```

→

```text
input (OCR).pdf
```

Nếu file tồn tại:

```text
input (OCR 2).pdf
input (OCR 3).pdf
```

Không overwrite im lặng.

Có setting:

```text
Output folder:

○ Same folder as input
○ Custom folder
```

---

# 2.5. Main OCR settings

Phần setting thường dùng:

### Language

```text
Vietnamese
English
Vietnamese + English
Custom
```

### Auto rotate

Map tới chức năng:

```text
rotate_pages
```

### Fix tilted pages

Map:

```text
deskew
```

OCRmyPDF phân biệt `rotate-pages` cho orientation sai 90/180/270 độ và `deskew` cho scan chỉ bị nghiêng nhẹ.

---

# 2.6. OCR Mode

Tạo dropdown:

```text
OCR Mode
```

Options:

### Skip existing text

```text
mode = skip
```

Dùng cho PDF có vài trang đã có text.

### Redo OCR

```text
mode = redo
```

Thay OCR layer cũ.

### Force OCR

```text
mode = force
```

Rasterize rồi OCR lại.

Hiển thị tooltip giải thích.

OCRmyPDF v17 hiện gom các hành vi này vào `--mode skip`, `redo`, `force`; các flag cũ vẫn là alias.

---

# 2.7. Presets

Tạo ba preset dễ hiểu.

### Quick

```text
auto rotate OFF
deskew OFF
optimization low
```

Ưu tiên tốc độ.

### Standard

```text
Vietnamese + English
auto rotate ON
deskew ON
normal optimization
```

Default.

### Difficult Scan

```text
auto rotate ON
deskew ON
oversample
OCR timeout cao hơn
```

Không tự bật các filter có khả năng phá hình.

Đặc biệt **không mặc định bật `clean-final` hoặc remove-background**, vì OCRmyPDF cảnh báo các chức năng xử lý ảnh này có thể tạo artifact hoặc loại mất nội dung.

---

# GIAI ĐOẠN 3 — PROGRESS, PAGE CONTROL, ERROR RECOVERY

Đây là phần quan trọng nhất.

Trường hợp thực tế cần giải quyết là PDF hàng trăm trang có thể chạy bình thường tới một trang nào đó rồi rất lâu.

## 3.1. Progress screen

Khi OCR:

```text
Giáo trình CNXHKH.pdf

OCR processing

██████████████░░░░░░░░░░░░░░░

Page 51 / 382
13%

Elapsed: 04:32
Estimated remaining: 28:14

Current stage:
Recognizing text

[ Cancel ]
```

Hiển thị:

```text
Current page
Total pages
Percent
Current stage
Elapsed time
Estimated remaining
Average seconds/page
```

ETA nên là moving average, không lấy average toàn job một cách cứng nhắc.

---

# 3.2. Stages

Progress có thể hiển thị các stage như:

```text
Analyzing PDF
Preprocessing
Detecting orientation
Deskewing
OCR
Generating PDF
Optimizing
Finalizing
```

Không để người dùng tưởng app treo khi OCR xong nhưng đang optimize.

---

# 3.3. Problem page detection

Nếu một page chạy quá lâu:

```text
Page 51 is taking longer than usual.
```

Nếu timeout:

```text
OCR skipped on page 51 because it exceeded the configured timeout.

The original page will remain in the output PDF.
```

Expose setting:

```text
Maximum OCR time per page
```

Default:

```text
180 seconds
```

Options:

```text
30 sec
60 sec
120 sec
180 sec
300 sec
Unlimited / advanced
```

OCRmyPDF có `tesseract-timeout`; trang bị skip bởi timeout sẽ không có OCR text tương ứng trong sidecar.

---

# 3.4. Page Range

Đây là feature bắt buộc.

Cho phép:

```text
All pages
```

hoặc:

```text
Selected pages
```

Input:

```text
1-50,52-100
```

hoặc:

```text
3-end
```

OCRmyPDF hỗ trợ page list/range như `2,3,13-17` và token `end`.

Validate input ngay trong GUI.

Sai:

```text
1--50
abc
52-20
```

thì báo trước khi chạy.

---

# 3.5. Exclude Pages

Thêm một UI thân thiện hơn:

```text
Pages to exclude:
[ 51,124 ]
```

App tự convert thành page selection tương ứng.

Ví dụ file 200 trang:

```text
exclude = 51
```

→

```text
1-50,52-end
```

Rất hữu ích cho scan lỗi.

---

# 3.6. Retry

Nếu job fail:

```text
OCR failed on page 51
```

hiện:

```text
[ Retry ]
[ Retry without page 51 ]
[ Change settings ]
[ View log ]
```

Không bắt người dùng tự mở terminal.

---

# 3.7. Cancel

Nút Cancel phải:

1. gửi terminate signal cho worker;
2. chờ graceful shutdown;
3. nếu worker không thoát thì kill;
4. cleanup temporary files;
5. giữ GUI responsive;
6. đánh dấu job `Cancelled`.

Không để lại process Tesseract zombie nếu có thể tránh.

---

# 3.8. Pause

**Không cần true pause giữa một PDF trong MVP.**

Không giả vờ pause bằng cách suspend process tùy tiện.

Chỉ hỗ trợ:

```text
Pause Queue
```

nghĩa là:

```text
job hiện tại hoàn tất
→ không chạy job tiếp theo
```

Sau này mới nghiên cứu resume giữa file.

---

# GIAI ĐOẠN 4 — ADVANCED FEATURES + PACKAGING

## 4.1. Batch Processing

Cho phép queue:

```text
Book 1.pdf
Book 2.pdf
Book 3.pdf
...
Book 50.pdf
```

Mặc định xử lý **mỗi lúc một PDF** để tránh ăn sạch RAM/CPU.

Advanced option:

```text
Concurrent files:
1
```

Không khuyến khích >1.

OCRmyPDF bản thân có worker processes và tham số giới hạn jobs, vì vậy không nên vô tình tạo quá nhiều tầng parallelism.

---

# 4.2. CPU usage

Advanced:

```text
CPU workers
Auto
1
2
4
8
```

Map đến:

```text
jobs
```

Default:

```text
Auto
```

---

# 4.3. Sidecar TXT

Checkbox:

```text
☐ Also export recognized text (.txt)
```

Output:

```text
book (OCR).pdf
book (OCR).txt
```

OCRmyPDF hỗ trợ sidecar text song song với output PDF.

---

# 4.4. Output type

Advanced:

```text
Output format

Auto
PDF
PDF/A
```

Default:

```text
Auto
```

Không bắt user phổ thông phải hiểu PDF/A.

---

# 4.5. Optimization

Setting:

```text
PDF optimization

None
Standard
High
Maximum
```

Map:

```text
0
1
2
3
```

Default:

```text
Standard
```

OCRmyPDF hiện dùng optimization level `0–3`, với `1` là mặc định.

---

# 4.6. Logs

Main screen chỉ hiện lỗi dễ hiểu.

Có nút:

```text
View detailed log
```

Mở drawer/panel:

```text
13:42:01 Loading PDF
13:42:04 Page 1 complete
...
13:46:20 Page 51 Tesseract timeout
...
```

Actions:

```text
Copy log
Save log
Clear
```

Không spam terminal ngoài app.

---

# 4.7. History

Lưu lịch sử gần đây:

```text
Input
Output
Date
Duration
Pages
Status
Settings
```

Ví dụ:

```text
Giáo trình.pdf
Completed
382 pages
21m 42s
vie+eng
```

Cho phép:

```text
Open output
Open folder
Run again
Remove from history
```

Lưu bằng JSON hoặc SQLite.

Nếu history bắt đầu phức tạp, dùng SQLite.

---

# 4.8. Settings persistence

Lưu:

```text
language
output folder
OCR mode
timeout
preset
jobs
output type
optimization
window size
theme
```

Dùng:

```text
QSettings
```

hoặc config JSON nếu kiến trúc phù hợp hơn.

---

# 4.9. First Run Setup

Lần đầu mở app:

```text
Welcome to OCRmyPDF GUI

Checking OCR components...
```

Sau đó:

```text
OCRmyPDF          ✓
Tesseract         ✓
English           ✓
Vietnamese        ✕
```

Nếu thiếu component:

```text
Fix
Locate manually
Refresh
```

Không tự tải/chạy installer hệ thống mà không hỏi user.

---

# 4.10. Language installation helper

Nếu thiếu `vie`:

```text
Vietnamese language pack is missing.
```

Có:

```text
[ Installation instructions ]
```

Hoặc nếu triển khai download tự động:

```text
[ Install Vietnamese ]
```

Nhưng phải:

- tải từ nguồn chính thức;
- kiểm tra lỗi download;
- xử lý permission `Program Files`;
- không yêu cầu chạy toàn app bằng Administrator;
- nếu cần elevation thì chỉ elevate đúng helper operation.

---

# 4.11. PDF Information

Khi select một PDF, hiện:

```text
382 pages
84.3 MB
Scanned PDF
No searchable text detected
```

Nếu có text:

```text
Text already detected on some pages
```

Có thể dùng pikepdf/PDF inspection để lấy metadata.

---

# 4.12. File safety

Bắt buộc:

- không modify input file trừ khi user chủ động chọn overwrite;
- output trước tiên ghi vào temporary path;
- chỉ move/rename thành output chính khi OCR thành công;
- tránh file output corrupt khi app crash;
- xử lý path Unicode;
- xử lý tên tiếng Việt;
- xử lý dấu ngoặc;
- xử lý spaces;
- xử lý path rất dài trên Windows nếu có thể.

Test bắt buộc với:

```text
Giáo trình CNXHKH (bản cũ).pdf
```

---

# 4.13. System Tray — không cần

Không cần tray icon.

Đây là utility chạy khi cần.

---

# 4.14. Packaging

Tạo build Windows:

```text
OCRmyPDF-GUI.exe
```

Ưu tiên:

```text
PyInstaller
```

Build đầu tiên nên dùng:

```text
onedir
```

thay vì onefile để:

- startup nhanh hơn;
- debug dependency dễ hơn;
- tránh extraction mỗi lần chạy.

Khi project ổn định mới cân nhắc:

```text
onefile
```

---

# 4.15. Dependency strategy

Cần phân biệt rõ:

### Bundled Python dependencies

Có thể bundle:

```text
PySide6
Python runtime
GUI code
OCR integration code
```

### External dependencies

Tesseract/Ghostscript có thể:

```text
A. yêu cầu user cài
```

hoặc trong tương lai:

```text
B. tạo installer đầy đủ
```

**V1 ưu tiên A.**

App phải tự detect và hướng dẫn user nếu thiếu.

Không dành quá nhiều thời gian ngay từ đầu để tạo một installer khổng lồ chứa toàn bộ OCR stack.

---

# PROJECT STRUCTURE

Sắp xếp code sạch.

Ví dụ:

```text
ocrmypdf-gui/
│
├── app/
│   ├── main.py
│   │
│   ├── ui/
│   │   ├── main_window.py
│   │   ├── drop_zone.py
│   │   ├── job_widget.py
│   │   ├── progress_widget.py
│   │   ├── settings_dialog.py
│   │   └── log_panel.py
│   │
│   ├── core/
│   │   ├── job.py
│   │   ├── queue_manager.py
│   │   ├── ocr_worker.py
│   │   ├── ocr_options.py
│   │   ├── progress.py
│   │   └── page_ranges.py
│   │
│   ├── services/
│   │   ├── dependency_checker.py
│   │   ├── tesseract_service.py
│   │   ├── pdf_service.py
│   │   └── history_service.py
│   │
│   ├── models/
│   │   ├── job.py
│   │   └── settings.py
│   │
│   ├── utils/
│   │   ├── paths.py
│   │   ├── logging.py
│   │   └── exceptions.py
│   │
│   └── resources/
│
├── tests/
│   ├── test_page_ranges.py
│   ├── test_output_paths.py
│   ├── test_dependencies.py
│   ├── test_jobs.py
│   └── test_ocr_options.py
│
├── scripts/
│   └── build_windows.ps1
│
├── pyproject.toml
├── requirements.txt
├── README.md
├── LICENSE
└── .gitignore
```

Có thể thay đổi structure nếu Codex tìm được architecture hợp lý hơn, nhưng **không được nhét toàn bộ app vào một file `main.py`**.

---

# UX REQUIREMENTS

UI phải responsive.

Không bao giờ freeze khi OCR.

Main UI chỉ để các option thường dùng:

```text
Files
Language
Preset
Rotate
Deskew
Output
Start
```

Các option còn lại đưa vào:

```text
Advanced Settings
```

Tooltips phải giải thích bằng ngôn ngữ bình thường.

Ví dụ không chỉ ghi:

```text
--deskew
```

mà ghi:

```text
Fix tilted pages

Straightens pages that were scanned slightly crooked.
```

---

# ERROR HANDLING

Tạo error mapping.

Ví dụ:

```text
MissingDependencyError
```

→

```text
Tesseract OCR could not be found.
```

```text
PriorOcrFoundError
```

→

```text
This PDF already contains text.

Choose Skip existing text, Redo OCR or Force OCR.
```

```text
OutputFileAccessError
```

→

```text
The output PDF is currently open in another application.
Close it and try again.
```

```text
TesseractConfigError
```

→

```text
The selected OCR language is not installed.
```

Không hiển thị Python traceback cho user bình thường.

Traceback chỉ vào detailed log.

OCRmyPDF cung cấp các exception/exit codes riêng như `MissingDependencyError`, `PriorOcrFoundError`, `OutputFileAccessError` và `TesseractConfigError`, nên hãy map chúng thành thông báo UI.

---

# TESTING

Viết unit test cho:

```text
page range parser
exclude page conversion
output filename generation
duplicate filenames
settings serialization
OCR options conversion
dependency detection
job state transitions
```

Test integration:

### Test 1

PDF 10 trang scan bình thường.

Expected:

```text
10 pages completed
searchable output
```

### Test 2

PDF tiếng Việt.

```text
vie
```

### Test 3

```text
vie+eng
```

### Test 4

Page range:

```text
1-5,7-end
```

### Test 5

File có text sẵn.

Test:

```text
skip
redo
force
```

### Test 6

Tesseract thiếu `vie`.

GUI phải báo rõ.

### Test 7

Output PDF đang mở.

Không crash.

### Test 8

Cancel OCR giữa chừng.

Worker phải kết thúc.

GUI vẫn dùng được.

### Test 9

PDF vài trăm trang.

Không leak RAM nghiêm trọng.

GUI không freeze.

---

# ACCEPTANCE CRITERIA

Project chỉ được coi là hoàn thành khi flow này hoạt động:

```text
Open app
↓
Drag PDF
↓
App detect số trang
↓
Select Vietnamese + English
↓
Enable Auto Rotate
↓
Enable Deskew
↓
Start OCR
↓
Progress hiển thị từng giai đoạn
↓
Có thể Cancel
↓
OCR hoàn thành
↓
Output:
filename (OCR).pdf
↓
Click Open PDF
↓
Text có thể Ctrl+F / select / copy
```

Ngoài ra:

```text
không terminal window
không GUI freeze
không mất input file
không overwrite im lặng
không để lại file tạm sau khi hoàn thành hoặc hủy
path tiếng Việt hoạt động
batch queue hoạt động
thiếu language pack được báo rõ
worker crash không làm GUI crash
```

---

# DEVELOPMENT ORDER

Triển khai theo thứ tự sau:

```text
1. Khởi tạo project và dependency
2. Dependency checker
3. Tesseract language detection
4. PDF metadata inspection
5. Page range parser
6. Output path generator
7. OCR options model
8. OCR worker process
9. Structured IPC events
10. Queue manager
11. GUI main window
12. Drag & drop và file queue
13. Progress screen
14. Cancel và queue pause
15. Error mapping và detailed logs
16. Presets và settings persistence
17. History
18. Batch processing
19. Unit tests và integration tests
20. PyInstaller onedir build
21. Windows smoke test
```

Mỗi giai đoạn phải chạy được và được kiểm thử trước khi chuyển sang giai đoạn kế tiếp.

---

# RULES FOR CODEX

- Trước khi viết code, kiểm tra môi trường Python và các dependency hiện có.
- Đọc tài liệu/API version đang cài thay vì đoán tên tham số.
- Không tạo UI giả nếu backend chưa chạy thật.
- Không block GUI thread.
- Không dùng `shell=True` nếu không cần.
- Dùng `pathlib.Path` cho mọi thao tác đường dẫn.
- Validate input trước khi khởi chạy worker.
- Dùng temporary output rồi mới commit output cuối cùng.
- Mọi subprocess phải có timeout, logging và cleanup phù hợp.
- Không nuốt exception; chuyển lỗi thành event có cấu trúc.
- Không hiển thị traceback thô cho người dùng phổ thông.
- Viết test cho phần parser, path, state machine và options trước khi nối vào UI.
- Sau mỗi mốc lớn, chạy test và sửa lỗi trước khi tiếp tục.
- Cập nhật `README.md` với hướng dẫn cài Tesseract, Ghostscript, language pack và chạy app.
- Ghi rõ giới hạn của MVP, đặc biệt về pause/resume giữa một PDF.
- Cuối cùng tạo bản build Windows và kiểm tra trên máy không có môi trường development.

---

# DELIVERABLES

Kết quả cuối cùng phải gồm:

```text
Source code hoàn chỉnh
Unit tests
Integration tests tối thiểu
README.md
requirements/pyproject configuration
PyInstaller build script
Windows onedir build
Hướng dẫn cài dependency
Hướng dẫn sử dụng nhanh
```

Khi báo cáo tiến độ, luôn nêu:

```text
Đã hoàn thành phần nào
Đã kiểm thử bằng cách nào
Còn vấn đề nào
Bước tiếp theo là gì
```

Mục tiêu cuối cùng là người dùng chỉ cần:

```text
Mở OCRmyPDF GUI
Kéo PDF vào
Chọn ngôn ngữ
Bấm Start OCR
```

và nhận được một PDF có thể tìm kiếm, chọn và sao chép văn bản mà không phải mở terminal hay nhớ command line.
