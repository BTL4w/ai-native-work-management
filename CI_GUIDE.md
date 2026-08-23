# Hướng dẫn CI

Repository dùng GitHub Actions để kiểm tra mỗi Pull Request và mỗi lần đẩy code
lên nhánh `main`. Đây là **CI thuần túy**, chưa phải CD: workflow không deploy,
không đẩy Docker image lên registry và không truy cập môi trường production.

## Pipeline đang kiểm tra gì?

Workflow nằm tại `.github/workflows/ci.yml` và gồm ba job:

1. **Quality** cài dependency từ lockfile, chạy lint, typecheck, unit test của
   backend/frontend và kiểm tra riêng package AI (bao gồm format-check của AI).
2. **Database migrations** khởi động PostgreSQL tạm thời bằng Docker Compose,
   chạy Alembic tới migration mới nhất, phát hiện migration chưa sinh và chạy
   integration test với PostgreSQL.
3. **Container build** chỉ chạy khi hai job trên thành công, sau đó kiểm tra cấu
   hình Compose và build các image `backend-api`, `frontend`, `ai-worker`.

Pipeline dùng mock provider trong test mặc định nên **không cần OpenAI API key**.
Mỗi action bên thứ ba được cố định bằng commit SHA để hạn chế thay đổi ngoài ý
muốn. Workflow có quyền GitHub tối thiểu là chỉ đọc nội dung repository.

## Chạy tương đương trên máy trước khi push

Từ thư mục gốc repository trong Ubuntu WSL2:

```bash
make install
make lint
make typecheck
make test
make ai
make migration-check
make containers-config-check
make containers-build
```

`make migration-check` cần Docker đang chạy và sẽ dùng service PostgreSQL trong
`compose.yaml`. Khi muốn dọn container và volume test cục bộ:

```bash
docker compose down --volumes
```

Không cần chạy `make containers-up` trong CI. Lệnh đó dành cho việc chạy và thử
toàn bộ ứng dụng trên máy phát triển; CI chỉ cần chứng minh các image build được.

## Bật CI trên GitHub

1. Push commit chứa workflow lên GitHub.
2. Mở tab **Actions** của repository và chọn workflow **CI**. Nếu GitHub hỏi,
   chọn bật Actions cho repository.
3. Có thể chọn **Run workflow** để chạy thủ công trên `main`; sau đó mọi Pull
   Request vào `main` và mọi push lên `main` sẽ tự chạy.
4. Khi cả ba job có dấu xanh, commit đã qua cổng CI. Dấu đỏ có thể mở ra để xem
   chính xác step và log bị lỗi.

Codex chỉ commit tại local trong bước này. Bạn vẫn cần chủ động push khi muốn
workflow xuất hiện và chạy trên GitHub.

## Chặn merge khi CI lỗi

Sau khi workflow đã chạy ít nhất một lần:

1. Vào **Settings → Rules → Rulesets** (hoặc **Branches** trên giao diện cũ).
2. Tạo rule áp dụng cho nhánh `main`.
3. Bật yêu cầu Pull Request trước khi merge.
4. Bật **Require status checks to pass** và chọn ba check của workflow CI:
   `Quality`, `Database migrations`, `Container build`.
5. Bật yêu cầu branch phải cập nhật với `main` trước khi merge nếu dự án có
   nhiều nhánh làm việc song song.

Không nên bật “required check” trước lần chạy đầu tiên vì GitHub có thể chưa đưa
tên các check vào danh sách lựa chọn.

## Khi CI báo lỗi

| Job lỗi | Kiểm tra đầu tiên ở local |
| --- | --- |
| Quality | Chạy lại đúng lệnh trong step đỏ: format, lint, typecheck hoặc test |
| Database migrations | Kiểm tra Docker, migration Alembic và integration test |
| Container build | Chạy `make containers-config-check` rồi `make containers-build` |

Không sửa workflow để bỏ qua test đang đỏ. Hãy tái hiện lỗi bằng lệnh tương ứng,
sửa nguyên nhân, rồi push commit mới để GitHub tự chạy lại.

## Khi nào mới thêm CD hoặc Jenkins?

CI này phù hợp để dùng ngay trong giai đoạn Core MVP. Chỉ thêm CD sau khi Core
MVP Exit Gate trong `PLAN.md` đạt yêu cầu và Deployment Track được chủ động kích
hoạt. Khi đó mới lần lượt học và triển khai registry/image tagging, môi trường
staging, secrets/environments, rollback; Kubernetes/kind, Jenkins và GKE thuộc
các bước hậu MVP, không nằm trong pipeline hiện tại.
