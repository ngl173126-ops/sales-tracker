# Partner Sales Tracker — hướng dẫn public lên Streamlit

App lưu dữ liệu trong 1 Google Sheet riêng tư. Code để trên GitHub (public), app chạy trên Streamlit Community Cloud và có link vĩnh viễn. Lần đầu setup mất khoảng 30–45 phút.

**Cần có:** tài khoản Google, GitHub, Streamlit (share.streamlit.io, đăng nhập bằng GitHub).

---

## Bước 1 — Tạo Google Sheet chứa dữ liệu
1. Mở **sheets.new** để tạo một Sheet mới, đặt tên ví dụ `Sales Tracker DB`.
2. Vào **File → Import → Upload**, chọn file `leads_seed.xlsx` (123 lead cũ đã chia sẵn cho Mạnh, Gấu, Trà, Cá), rồi chọn **Replace spreadsheet**.
3. Kiểm tra tab dưới cùng tên là **`leads`**. Copy link Sheet trên thanh địa chỉ để dùng ở Bước 4.

> Không sửa hay đổi tên dòng tiêu đề (dòng 1). Có thể sửa dữ liệu trực tiếp trên Sheet nếu cần.

## Bước 2 — Tạo "tài khoản robot" để app được đọc/ghi Sheet
1. Vào **console.cloud.google.com**, bấm chọn project ở góc trên, chọn **New project**, đặt tên `sales-tracker` rồi bấm **Create**.
2. Gõ **Google Sheets API** vào ô tìm kiếm trên cùng, mở ra rồi bấm **Enable**.
3. Vào menu **IAM & Admin → Service Accounts → + Create service account**, đặt tên `sales-bot`, bấm **Create and continue**, rồi bấm **Done**.
4. Bấm vào `sales-bot` vừa tạo, mở tab **Keys → Add key → Create new key → JSON → Create**. Máy sẽ tải về 1 file `.json`.
   ⚠️ File này giống mật khẩu: **không** upload lên GitHub, không gửi cho ai.
5. Mở file JSON, copy dòng `client_email` (dạng `sales-bot@...iam.gserviceaccount.com`).
6. Quay lại Google Sheet, bấm **Share**, dán email đó vào, chọn quyền **Editor**, bỏ tick *Notify* rồi bấm **Share**.

## Bước 3 — Đưa code lên GitHub
1. Vào github.com, bấm **+ → New repository**, đặt tên `sales-tracker`, chọn **Public**, tick **Add a README**, rồi bấm **Create**.
2. Bấm **Add file → Upload files**, kéo `app.py` và `requirements.txt` vào, rồi bấm **Commit changes**.
3. (Tuỳ chọn, để có màu giao diện) Bấm **Add file → Create new file**, gõ tên `.streamlit/config.toml`, dán nội dung file `config.toml` vào, rồi bấm **Commit**.

## Bước 4 — Deploy trên Streamlit
1. Vào **share.streamlit.io**, bấm **Create app → Deploy a public app from GitHub**.
2. Chọn repo `sales-tracker`, branch `main`, main file `app.py`.
3. Bấm **Advanced settings → Secrets** và dán đoạn dưới đây, thay 3 chỗ trong ngoặc:

```toml
sheet_url = "(link Google Sheet ở Bước 1)"
app_password = "(mật khẩu chung của team)"
gcp_json = '''
(mở file .json ở Bước 2, copy TOÀN BỘ nội dung, dán vào đây)
'''
```
4. Bấm **Deploy**. Chờ 2–5 phút là có link dạng `https://ten-app.streamlit.app`.

## Bước 5 — Gửi cho team
- Gửi link kèm mật khẩu. Mỗi người chọn tên mình ở thanh bên trái, link sẽ tự thêm `?me=Tên`. **Lưu lại link đó**, lần sau mở là vào thẳng danh sách của mình.
- Cần sửa code thì sửa `app.py` trên GitHub rồi Commit, app tự cập nhật sau 1–2 phút.
- Đổi thành viên team: sửa dòng `TEAM = [...]` ở đầu `app.py`.
- Đổi số ngày nhắc lại: sửa `REMIND_DAYS = 3`.

## Lỗi hay gặp
| Hiện tượng | Cách sửa |
|---|---|
| `PermissionError` / 403 | Chưa share Sheet cho `client_email` với quyền Editor (Bước 2.6) |
| `SpreadsheetNotFound` | Sai `sheet_url` trong Secrets |
| "Google Sheets API has not been used…" | Chưa bấm Enable Sheets API (Bước 2.2) |
| Lỗi đọc Secrets / JSON | Kiểm tra lại 3 dấu `'''` trước và sau nội dung JSON |
| Thanh bên hiện "chế độ thử" | Secrets chưa có `gcp_json` hoặc `sheet_url` |
| App "ngủ" khi lâu không ai dùng | Bình thường với bản miễn phí, bấm nút đánh thức rồi chờ khoảng 30 giây |

## Bảo mật
- Repo GitHub công khai nhưng **chỉ chứa code**. Dữ liệu lead nằm trong Google Sheet riêng.
- Ai có link app đều mở được, nên **hãy đặt `app_password`** để bảo vệ thông tin liên hệ của khách hàng.
