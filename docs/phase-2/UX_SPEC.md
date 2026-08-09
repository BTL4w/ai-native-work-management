# Phase 2 UX Specification — Conversation-First AI Assistant and Planning Proposal

## 1. Mục tiêu của bước thiết kế

Tài liệu này chốt trải nghiệm người dùng của Phase 2 trước khi thiết kế technical
foundation, API, database hoặc workflow AI. Kết quả chính cần demo được là:

```text
Người dùng mở Trợ lý AI
→ bắt đầu hoặc tiếp tục một conversation
→ hỏi bằng tiếng Việt hoặc tiếng Anh mà không chọn workflow
→ Agent Harness route từng turn theo intent và quyền
→ Employee nhận câu trả lời read-only về Project/Task được phép
hoặc Manager mô tả một mục tiêu planning
→ AI hỏi lại assumption/thông tin thiếu bằng card
→ AI tạo Project proposal có Mục tiêu/Milestone/Task/Dependency/Acceptance Criteria
→ Manager sửa proposal bằng card hoặc chat
→ deterministic validation chạy lại
→ Manager xem diff rồi Approve hoặc Reject
→ chỉ Approve thành công mới tạo business records
```

Phase 2 đồng thời bổ sung các màn hình Planning thủ công. Manager phải tạo và
duy trì Mục tiêu dự án, Milestone, Task Dependency và Acceptance Criteria được
ngay cả khi model provider bị tắt hoặc không khả dụng.

Đây là UX specification và wireframe low-fidelity. Nó chốt hành vi, quyền, trạng
thái và nội dung cần quan sát; không khóa màu sắc, typography hoặc implementation
chi tiết.

## 2. Quyết định trải nghiệm đã chốt

- Sidebar ứng dụng dùng nhãn trung lập `Trợ lý AI`, không dùng `AI Planning`.
- Trợ lý AI là một chat app toàn trang dành cho mọi authenticated role; Phase 2
  chưa có chat drawer/sidebar nhỏ nổi trên mọi màn hình.
- Trang có action `Cuộc trò chuyện mới`. Conversation là container của transcript
  và có thể chứa nhiều user/assistant turn; nó không đồng nhất với planning run.
- Chat là đầu vào tự nhiên; không dùng form-first với nút `Tạo kế hoạch`.
- Người dùng không chọn workflow. Agent Harness route mỗi turn theo intent,
  capability đang bật, tenant, role và resource permission.
- AI phản hồi bằng card có cấu trúc và một wizard tuần tự trong cuộc hội thoại.
- Phase 2 bật read-only Project/Task Q&A cho mọi role và planning workflow cho
  Admin/Manager. Yêu cầu assignment recommendation, persisted daily
  update, risk hoặc report phải được báo là chưa khả dụng và dẫn về flow thủ công
  phù hợp nếu flow đó đã tồn tại.
- Chat là command surface, không phải nơi duy nhất quản lý dữ liệu. Business data
  sau approval xuất hiện trong các màn hình Project, Milestone và Task.
- Không có navigation `Goals` riêng. Goal vẫn là entity có version/audit nhưng
  được trình bày là section `Mục tiêu dự án` trong Project detail.
- Danh sách bên trái của trang Trợ lý AI là các conversation gần đây. Planning
  run chỉ là execution reference nội bộ của một turn và không được dùng làm mô
  hình điều hướng chính.

Quyết định dùng trang riêng là phạm vi được duyệt cho Phase 2. Persistent chat
sidebar trong product vision có thể được bổ sung ở một phase sau; Phase 2 không
tạo placeholder behavior cho các workflow chưa được kích hoạt.

## 3. Phạm vi

### Có trong Phase 2

- Mục tiêu dự án, Milestone, Task Dependency và Acceptance Criteria thủ công.
- Tab `Plan` trong Project detail và các section planning trong Task detail.
- Trang `Trợ lý AI` dành cho mọi authenticated role.
- Chat input tiếng Việt/Anh để bắt đầu hoặc tiếp tục conversation.
- Employee read-only Q&A về Project/Task được phép, gồm task đang làm, task tiếp
  theo, status, deadline, dependency và Acceptance Criteria.
- Bounded intent routing cho `work.read`, `planning.create` và availability
  response; không có workflow picker.
- Planning wizard bằng structured cards trong hội thoại.
- Assumption, missing-information, proposal, validation, diff và approval cards.
- Chỉnh proposal trực tiếp trên card hoặc yêu cầu sửa bằng chat.
- Proposal versioning có biểu diễn nguồn AI và phần Manager đã sửa.
- Workflow progress một chiều và khả năng resume planning run.
- Approve/reject toàn bộ proposal.
- Manual fallback khi provider, structured output hoặc verifier thất bại.
- Loading, empty, unavailable, validation, stale, forbidden, conflict và
  unexpected-error states.
- Nhãn giao diện thông qua translation key cho tiếng Việt và tiếng Anh.

### Không có trong Phase 2

- Sidebar chat nhỏ luôn hiện trên mọi màn hình.
- Unrestricted general-purpose Ask/Analyze/Simulate/Act execution. Phase 2 chỉ
  route những capability đã đăng ký và trả availability card cho capability
  tương lai.
- Assignee recommendation, workload, skill, capacity hoặc leave.
- AI daily update, blocker, risk explanation hoặc notification.
- AI management report, feedback loop hoặc production evaluation dashboard.
- Calendar, document ingestion, Qdrant, hybrid retrieval hoặc GraphRAG.
- Self-hosted inference, training, fine-tuning hoặc distillation.
- Automatic assignment, autonomous execution hoặc autonomous replanning.
- Partial approval theo từng Milestone/Task; Phase 2 dùng một quyết định cho toàn
  proposal sau khi Manager chỉnh phạm vi mong muốn.

## 4. Vai trò và quyền nhìn thấy trên UI

| Hành động | Admin (như Manager) | Manager | Employee |
| --- | --- | --- | --- |
| Xem Mục tiêu/Milestone của Project được phép | Có | Có | Có |
| Tạo/sửa/xóa Mục tiêu và Milestone thủ công | Có | Có | Không |
| Tạo/sửa/xóa Dependency và Acceptance Criteria thủ công | Có | Có | Không |
| Xem Dependency/Acceptance Criteria của task được phép | Có | Có | Có |
| Mở Trợ lý AI và tạo/tiếp tục conversation | Có | Có | Có |
| Hỏi read-only về Project/Task được phép | Có | Có | Có |
| Khởi tạo planning proposal từ chat | Có | Có | Không |
| Chỉnh AI proposal | Có | Có | Không |
| Approve hoặc Reject AI proposal | Có | Có | Không |

Manual Manager mutation hợp lệ ghi trực tiếp sau authorization, validation và
audit; UI không tạo approval cho thao tác thủ công thông thường. Mọi AI-proposed
write phải chờ approval.

Ẩn nút không thay thế authorization ở backend. Organization được resolve từ
authenticated membership; không form nào cho phép nhập `organization_id` tùy ý.
Employee gọi trực tiếp API AI hoặc mutation planning không có quyền phải nhận
structured `403` mà không được nâng quyền qua prompt hay tool call.

`Employee không được chỉnh sửa` trong contract này nghĩa là Employee không được
chỉnh Project Plan, Goal, Milestone, Dependency, assignment, proposal hoặc
approval. Quyền cập nhật trạng thái Task được giao từ Phase 1 vẫn giữ nguyên.
Khi Phase 4 được kích hoạt, Employee còn được sửa/xác nhận daily update của chính
mình trước khi lưu; đó là user-owned progress input, không phải Plan edit.

## 5. Mô hình điều hướng

```text
Application shell
├─ Projects
│  └─ Project detail
│     ├─ Overview/Tasks
│     └─ Plan
│        ├─ Mục tiêu dự án
│        └─ Milestones
├─ My Tasks
│  └─ Task detail
│     ├─ Dependencies
│     └─ Acceptance Criteria
└─ Trợ lý AI                         (mọi authenticated role)
   ├─ Cuộc trò chuyện mới
   └─ Conversations gần đây
      └─ Transcript
         ├─ User/Assistant messages
         ├─ Read-only answer/evidence cards
         └─ Planning progress/proposal/approval cards khi được route
```

`Trợ lý AI` là một shell hội thoại dùng chung từ Phase 2 trở đi. Một conversation
có nhiều turn; một planning turn có thể tạo một bounded planning run, còn một
read-only turn có thể chỉ gọi typed query tools. UI không quảng bá capability
chưa tồn tại.

## 6. Planning thủ công

### 6.1. Mục tiêu dự án (Goal)

Manager xem, tạo và sửa Mục tiêu ngay trong tab `Plan` của Project detail. Phase
2 không có Goal list hoặc Goal detail độc lập. Mỗi Project có tối đa một Goal;
Project cũ được phép chưa có Goal. Goal thuộc đúng một Project và luôn cùng
organization với Project đó.

| Trường | Yêu cầu UX |
| --- | --- |
| Title | Bắt buộc; trim; lỗi cạnh trường |
| Description | Tùy chọn; multiline |
| Expected outcomes | Danh sách có thể thêm, sửa và xóa |

Các giới hạn độ dài và relation chính xác được chốt ở technical foundation. UI
không tự tạo invariant khác backend.

### 6.2. Milestone

Manager quản lý Milestone trong tab `Plan` của Project detail.

| Trường | Yêu cầu UX |
| --- | --- |
| Title | Bắt buộc |
| Description | Tùy chọn |
| Target date | Tùy chọn; hiển thị theo locale |

Nếu Project có khung ngày, UI cảnh báo ngày Milestone nằm ngoài khung; domain
validation quyết định có được lưu hay không.

### 6.3. Task Dependency

Task detail hiển thị `Depends on` và `Blocks`. Manager có thể thêm hoặc xóa một
dependency bằng cách chọn Task trong cùng Project và organization.

- Không cho chọn chính Task hiện tại.
- Không cho tạo cạnh trùng.
- Dependency tạo cycle bị từ chối bằng lỗi xác định được.
- Không kéo Task khác organization vào danh sách lựa chọn.

### 6.4. Acceptance Criteria

Task detail hiển thị danh sách Acceptance Criteria. Manager có thể thêm, sửa,
xóa và sắp xếp tiêu chí. Employee có quyền xem Task được thấy tiêu chí nhưng
không sửa trong Phase 2.

Mỗi tiêu chí là một phát biểu có thể kiểm tra. Phase 2 chưa thêm workflow đánh
dấu đạt/chưa đạt, evidence hoặc completion policy mới.

## 7. Trợ lý AI — entry và chat behavior

### 7.1. Empty/new-chat state

Trang mới gồm:

- Tiêu đề `Trợ lý AI`.
- Danh sách conversation gần đây, tên được tạo từ nội dung an toàn của những
  turn đầu và không lộ resource mà actor không còn quyền xem.
- Transcript rỗng có lời chào phù hợp role và mô tả capability đang bật.
- Một ô chat multiline với action gửi và hỗ trợ bàn phím.
- Prompt mẫu đa domain bằng translation resource.
- Composer cố định ở cuối khung chat; transcript cuộn độc lập và tự theo dõi tin
  mới chỉ khi người dùng đang ở gần cuối.

Không có nút chọn workflow. Manager gửi một yêu cầu tự nhiên, ví dụ:

> Lập kế hoạch tổ chức hội thảo khách hàng trong tám tuần cho 300 người.

Employee có thể hỏi, ví dụ:

> Tôi đang làm task nào và task tiếp theo là gì?

Sau khi server commit user message và assistant turn, message của người dùng
xuất hiện trong transcript. Một planning intent hợp lệ có thể liên kết turn với
planning run riêng; read-only Q&A không cần giả lập planning run. Submit retry
dùng cùng idempotency key cho cùng một ý định gửi.

### 7.2. Transcript và turn behavior

- Mỗi user message tạo đúng một assistant turn idempotent.
- Assistant turn có trạng thái `QUEUED`, `RUNNING`, `NEEDS_INPUT`, `COMPLETED`
  hoặc `FAILED` và có thể liên kết một workflow run.
- Prose, progress và card đều là typed content block của assistant message;
  frontend không suy diễn lifecycle từ text do model tạo.
- Một conversation có thể chuyển intent giữa các turn. Context Builder chỉ tải
  history tối thiểu cần thiết và luôn resolve lại tenant/permission/source
  freshness.
- Retry không tạo trùng user message, assistant message hoặc workflow run.
- Người dùng có thể reload và dựng lại transcript từ REST; SSE chỉ thông báo có
  event/message mới.

### 7.3. Intent và capability Phase 2

Phase 2 đăng ký ba route xác định:

| Route | Role | Hành vi |
| --- | --- | --- |
| `work.read` | Admin/Manager/Employee | Trả lời từ typed Project/Task read tools theo quyền |
| `planning.create` | Admin/Manager | Khởi tạo/resume bounded planning workflow |
| `capability.unavailable` | Mọi role | Nêu capability chưa được kích hoạt, không giả lập kết quả |

Employee yêu cầu planning hoặc mutation không có quyền phải nhận response an
toàn, không được tạo run/proposal. Read-only answer phải chỉ ra nguồn business
record và trạng thái unknown/stale khi không đủ dữ liệu; model không được tự tạo
fact.

### 7.4. Intent ngoài phạm vi

Nếu Manager yêu cầu capability Phase 3–5, Trợ lý AI phải trả một availability
card, không giả lập kết quả:

```text
Năng lực này chưa khả dụng trong Phase 2.
[Đi tới flow thủ công nếu đã có] [Bắt đầu kế hoạch mới]
```

Ví dụ: AI assignee recommendation, daily update extraction và report narrative
không được thực thi trong Phase 2.

### 7.5. Workflow progress

Planning turn hiển thị progress card có ý nghĩa ngay trong transcript thay vì
spinner vô hạn hoặc một stepper dashboard cố định:

```text
Đã nhận yêu cầu
→ Đang hiểu mục tiêu
→ Đang kiểm tra context và quyền
→ Cần Manager bổ sung thông tin | Đang tạo proposal
→ Đang deterministic validation
→ Proposal sẵn sàng
```

SSE chỉ phục vụ progress một chiều. Nếu stream mất kết nối, UI thông báo đang
kết nối lại và có thể lấy trạng thái run qua REST; mất stream không đồng nghĩa
workflow thất bại.

## 8. Structured-card wizard

Wizard sống trong transcript và gồm bốn stage. Mỗi stage là một assistant message
hoặc card mới theo thứ tự thời gian. Một progress/step summary nhỏ có thể nằm
trong card hiện tại, nhưng không được biến toàn trang thành bốn section cố định
hoặc bắt người dùng cuộn qua một dashboard. Manager có thể tham chiếu stage trước
bằng chat mà không mất draft.

### Stage 1 — Hiểu mục tiêu

AI hiển thị `Understanding card` gồm:

- Mục tiêu dự án được diễn giải lại.
- Expected outcomes.
- Phạm vi AI hiểu được.
- Dữ liệu nguồn/context được dùng ở mức có thể giải thích.
- Nội dung chưa biết được gắn nhãn `Unknown`, không tự điền thành fact.

Manager có thể xác nhận hoặc sửa bằng chat.

### Stage 2 — Assumptions và missing information

`Assumption card` phân biệt:

- Assumption do AI đề xuất.
- Thông tin còn thiếu.
- Câu hỏi bắt buộc phải trả lời.
- Câu hỏi tùy chọn có thể giữ `Unknown`.

Manager chỉnh field hoặc trả lời bằng chat. Nội dung chưa xác nhận không được
coi là business fact.

### Stage 3 — Chỉnh proposal

`Proposal card` nhóm nội dung:

- Project name, description, mục tiêu và expected outcomes.
- Milestones.
- Tasks thuộc từng Milestone hoặc Project.
- Task Dependencies.
- Acceptance Criteria.
- Assumptions và open questions còn lại.

Manager có thể:

- Mở từng nhóm để chỉnh field có cấu trúc.
- Thêm, sửa, xóa và sắp xếp Milestone, Task, Dependency và Criteria.
- Nhắn yêu cầu sửa bằng chat.
- Xem nhãn `AI proposed`, `Manager edited` và `Unknown`.

Task hiện dùng contract Phase 1 yêu cầu assignee. Phase 2 không cho AI đề xuất
assignee vì recommendation thuộc Phase 3. Mỗi Task proposal bắt đầu với
`Assignee: Chưa chọn`; Manager chọn thủ công một membership hợp lệ trước khi
approval. Đây là manual selection, không có ranking, workload hay AI explanation.

Mỗi lần chỉnh tạo proposal version mới và chạy validation lại. Nội dung version
trước vẫn có thể xem trong diff/audit nhưng không còn là version được duyệt.

`Nhờ AI chỉnh` gửi một user message mới trong cùng conversation và tạo một
assistant turn/revision mới. Card version cũ vẫn nằm trong transcript ở trạng
thái read-only/superseded; card version mới nêu rõ version và diff.

### Stage 4 — Review và quyết định

`Validation card` và `Approval card` hiển thị:

- Deterministic validation result.
- Error chặn approval và warning không chặn.
- Before/after diff so với AI draft trước hoặc proposal version trước.
- Assumption/open question còn lại.
- Proposal version đang được quyết định.
- Actions `Approve` và `Reject`.

Phase 2 dùng approval toàn bộ proposal. Manager muốn loại một phần phải quay lại
Stage 3, xóa phần đó, revalidate rồi approve version mới.

## 9. Quyền chỉnh sửa và metadata chỉ đọc

### Manager có thể chỉnh

- Project content, mục tiêu và expected outcomes.
- Assumptions và câu trả lời missing-information.
- Milestone content và target date.
- Task title, description, due date và assignee chọn thủ công.
- Dependency edges.
- Acceptance Criteria.
- Thứ tự các phần có hỗ trợ sắp xếp.

### Chỉ đọc

- Planning run/proposal/approval status.
- Proposal version và timestamp.
- Workflow, prompt, model và verifier version.
- Validation result và nguồn của validation.
- Before/after diff được hệ thống tạo.
- Audit/approval metadata.
- Context provenance được phép hiển thị.

Không hiển thị hidden chain-of-thought. Không hiển thị confidence nếu UI không
giải thích confidence đại diện điều gì và được tạo từ đâu.

## 10. Proposal và approval lifecycle

```text
RUNNING
→ NEEDS_INPUT
→ DRAFT
→ VALIDATING
→ READY_FOR_DECISION
→ APPROVED | REJECTED | FAILED
```

- `RUNNING`: model/workflow đang xử lý.
- `NEEDS_INPUT`: workflow pause tại human checkpoint.
- `DRAFT`: proposal có thể sửa; chưa đủ điều kiện approve.
- `VALIDATING`: deterministic verifier đang kiểm tra current version.
- `READY_FOR_DECISION`: version hiện tại hợp lệ và có approval đang chờ.
- `APPROVED`: business transaction đã commit đúng một lần.
- `REJECTED`: kết thúc không có business side effect.
- `FAILED`: workflow không tạo được proposal hợp lệ; manual fallback còn dùng
  được.

Proposal đã `APPROVED` hoặc `REJECTED` là read-only. Muốn thay đổi sau approval,
Manager dùng các manual business flows; Phase 2 chưa tự tạo replanning proposal.

### Approval guarantees thể hiện trên UX

- AI không thể tự approve.
- Nút Approve bị khóa khi có validation error, field bắt buộc chưa chọn hoặc
  proposal đang stale.
- Edit sau validation làm version cũ hết hiệu lực và yêu cầu validation lại.
- Nếu dữ liệu nguồn thay đổi trước decision, UI hiển thị conflict, tải context
  mới và yêu cầu review/revalidate.
- Approve retry không tạo record trùng.
- Chỉ báo thành công sau khi transaction, outbox và audit boundary hoàn tất.
- Reject không tạo Goal, Project, Milestone, Task, Dependency hoặc Criteria.

## 11. Manual fallback

Các trường hợp fallback gồm:

- Provider không được cấu hình hoặc đang unavailable.
- Model timeout.
- Structured output sai schema.
- Verifier từ chối output.
- Retry limit của workflow đã hết.

Chat hiển thị error card an toàn với request/reference ID và hai action khi phù
hợp: `Thử lại` và `Tiếp tục thủ công`.

`Tiếp tục thủ công` mở structured planning editor, giữ brief và chỉ prefill dữ
liệu đã vượt schema/deterministic validation. Raw malformed output không được
đưa vào business form như fact. Manager có thể hoàn thành kế hoạch bằng các
manual flows mà không cần provider.

## 12. Wireframes

### 12.1. Trợ lý AI — new chat

```text
┌─────────────┬───────────────┬───────────────────────────────┐
│ App nav     │ Conversations │ Trợ lý AI       [+ Chat mới] │
│             │               ├───────────────────────────────┤
│ Projects    │ Hội thảo      │                               │
│ My Tasks    │ Onboarding    │ Tôi có thể giúp gì cho bạn?  │
│ Trợ lý AI ● │ Task hôm nay  │                               │
│             │               │ Gợi ý theo role:              │
│ VI | EN     │               │ · Task tiếp theo là gì?       │
│             │               │ · Lập kế hoạch Project        │
│             │               ├───────────────────────────────┤
│             │               │ [ Nhắn cho Trợ lý AI... ] [↑]│
└─────────────┴───────────────┴───────────────────────────────┘
```

### 12.2. Assumption card

```text
┌─────────────────────────────────────────────────────────────┐
│ AI: Mình cần bạn xác nhận hai điểm trước khi lập kế hoạch. │
│                                                             │
│ Assumption                                                  │
│ [Tổ chức trực tiếp tại cùng thành phố              ] [Sửa] │
│                                                             │
│ Missing information                                         │
│ Ngân sách dự kiến                                           │
│ [Chưa xác định                                      ]       │
│                                                             │
│                               [Xác nhận và tiếp tục]         │
└─────────────────────────────────────────────────────────────┘
```

### 12.3. Proposal card — Stage 3

```text
┌─────────────────────────────────────────────────────────────┐
│ AI                                                          │
│ Tôi đã cập nhật kế hoạch theo yêu cầu mới của bạn.          │
│ 1 Hiểu ✓ · 2 Assumption ✓ · 3 Chỉnh plan · 4 Review       │
│ AI proposal · Draft v2                                     │
│                                                             │
│ Project & mục tiêu                               [Sửa]     │
│ Expected outcomes                                [Sửa]     │
│ Milestones (4)                                   [Mở]      │
│ Tasks (18) · 3 task chưa chọn assignee           [Mở]      │
│ Dependencies (12) · Không có cycle               [Sửa]     │
│ Acceptance Criteria (9)                          [Sửa]     │
│                                                             │
│ Validation: 3 field bắt buộc chưa hoàn tất                  │
│                  [Chỉnh tay] [Nhờ AI chỉnh] [Review]       │
└─────────────────────────────────────────────────────────────┘

Bạn
Rút thời gian còn sáu tuần và thêm bước kiểm tra địa điểm.

AI
[Proposal card · Draft v3 · diff so với v2]

───────────────────────────────────────────────────────────────
[ Nhắn cho Trợ lý AI...                                ] [↑]
```

### 12.4. Review và approval

```text
┌─────────────────────────────────────────────────────────────┐
│ Proposal v4 · Ready for decision                           │
├─────────────────────────────────────────────────────────────┤
│ Validation                                                 │
│ ✓ Required fields  ✓ Dates  ✓ Dependency graph  ✓ Tenant │
│                                                             │
│ Changes since AI draft                                     │
│ ~ Duration: 8 tuần → 6 tuần                               │
│ + Milestone: Kiểm tra địa điểm                              │
│ ~ 5 task được Manager chọn assignee                         │
│                                                             │
│ Không có business record nào được tạo trước approval.       │
│                               [Reject] [Edit] [Approve]      │
└─────────────────────────────────────────────────────────────┘
```

### 12.5. Manual planning

```text
Project detail / Plan
┌─────────────────────────────────────────────────────────────┐
│ Customer conference                                        │
│ Overview · Tasks · Plan ●                                  │
├─────────────────────────────────────────────────────────────┤
│ Mục tiêu dự án                              [Chỉnh sửa]     │
│ Build qualified customer engagement                         │
│ Expected outcomes                                  [Sửa]    │
│                                                             │
│ Milestones                                  [+ Milestone]   │
│ 1. Venue confirmed                         2026-09-10       │
│ 2. Invitations sent                        2026-09-24       │
└─────────────────────────────────────────────────────────────┘
```

## 13. Trạng thái giao diện dùng chung

Mọi view lấy dữ liệu có:

- `Loading`: skeleton/progress có accessible label.
- `Empty`: giải thích chưa có dữ liệu; CTA chỉ hiện khi actor có quyền.
- `Unavailable`: capability/provider không khả dụng và manual path tương ứng.
- `Needs input`: nêu field bắt buộc và giữ draft.
- `Validation error`: lỗi tại field/card và summary có thể focus.
- `Verifier rejected`: không hiển thị output như proposal hợp lệ.
- `Stale/Conflict`: giải thích dữ liệu nguồn hoặc version đã đổi; yêu cầu reload
  và revalidate.
- `Forbidden`: không suy đoán resource có tồn tại.
- `Not found`: resource không tồn tại hoặc không thể truy cập theo contract.
- `Disconnected`: workflow vẫn có thể chạy; hiển thị reconnect/poll state.
- `Unexpected error`: reference ID an toàn và action thử lại/fallback.

Transcript không biến mất khi turn lỗi. Error/progress card được append đúng vị
trí của turn; composer tiếp tục dùng được trừ khi policy yêu cầu chờ một decision
cụ thể. Reload phải dựng lại cùng message/card order từ PostgreSQL.

Mutation chỉ báo thành công sau khi server xác nhận. Lỗi authorization, audit,
outbox hoặc transaction không được hiển thị như thành công.

## 14. Accessibility và song ngữ

- Tất cả business UI text dùng translation key Việt/Anh.
- Stepper truyền đạt trạng thái bằng text/icon, không chỉ màu.
- Card có heading hierarchy và region label rõ.
- Edit, Add, Delete, Approve và Reject dùng được bằng bàn phím.
- Sau validation, focus chuyển tới error summary; link đưa tới field lỗi.
- Dialog approval/reject có focus trap và trả focus đúng action ban đầu.
- Progress update dùng live region không gây đọc lặp quá mức.
- Motion tôn trọng `prefers-reduced-motion`.
- Ngày hiển thị theo locale nhưng payload dùng dạng chuẩn hóa.

Translation key mẫu:

```text
nav.aiAssistant
ai.chat.new
ai.chat.placeholder
ai.conversation.new
ai.conversation.recent
ai.turn.status.running
ai.intent.unavailable
ai.answer.sources
ai.capability.planning
ai.run.status.running
ai.run.status.needsInput
ai.card.understanding
ai.card.assumptions
ai.card.proposal
ai.card.validation
ai.card.approval
ai.proposal.label.aiProposed
ai.proposal.label.managerEdited
ai.proposal.label.unknown
ai.action.continueManually
ai.action.retry
approval.action.approve
approval.action.reject
planning.projectGoal.title
planning.milestone.title
planning.dependency.title
planning.acceptanceCriteria.title
common.error.stale
common.error.unavailable
```

## 15. UX acceptance checklist

- Manager có thể hoàn thành manual Mục tiêu dự án/Milestone/Dependency/Criteria
  flow khi model provider bị tắt.
- Mọi authenticated role mở được cùng một full-page `Trợ lý AI`.
- `Cuộc trò chuyện mới` tạo conversation, không mặc định tạo planning run.
- Conversation list, chronological transcript và fixed composer có behavior như
  một chat app; planning run/stepper không phải layout chính.
- Manager nhập prompt tự nhiên, không phải chọn workflow hoặc dùng form-first.
- Employee hỏi được task đang làm, task tiếp theo, status, deadline,
  dependency và Acceptance Criteria từ dữ liệu được phép xem.
- Employee read-only Q&A không thể sửa Project/Plan/Task assignment hoặc approval.
- AI trả structured cards thay vì chỉ prose.
- Wizard có bốn stage: hiểu mục tiêu, assumptions, chỉnh proposal, review/decision.
- Manager có thể chỉnh bằng field hoặc chat và thấy proposal version/diff mới.
- `Nhờ AI chỉnh` tạo turn và proposal version mới trong cùng transcript; version
  cũ vẫn hiển thị read-only/superseded.
- Phase 2 không sinh hoặc xếp hạng assignee; Manager chọn thủ công để thỏa Task
  contract hiện tại.
- Approve bị khóa khi proposal invalid, incomplete hoặc stale.
- Không có Project/Milestone/Task được tạo trước Manager approval.
- Approval commit đúng một lần; Reject không có business side effect.
- Employee không truy cập được AI proposal/approval mutation.
- Provider timeout, malformed output và verifier rejection đều có manual fallback.
- Unknown, stale và unavailable được hiển thị rõ.
- UI có translation key và luồng đánh giá song ngữ Việt/Anh.
- Không có capability thuộc Explicit non-goals của Phase 2.

## 16. Các scenario cần kiểm thử từ UX

### Primary E2E

```text
Manager đăng nhập
→ mở Trợ lý AI và tạo chat mới
→ nhập mục tiêu
→ xác nhận assumption
→ nhận proposal card
→ chỉnh thời hạn và chọn assignee thủ công
→ xem validation/diff
→ approve
→ mở Project/Plan/Task detail
→ thấy Mục tiêu dự án, Milestone, Dependency và Acceptance Criteria đã tạo
```

Scenario này cần chạy bằng mock provider mặc định và có case Việt/Anh.

### Employee read-only assistant E2E

```text
Employee đăng nhập
→ mở cùng Trợ lý AI
→ hỏi "Tôi đang làm task nào và task tiếp theo là gì?"
→ nhận answer/evidence card chỉ chứa task được phép
→ thử yêu cầu chỉnh plan hoặc approve
→ nhận response không được phép và không có mutation/run/proposal nào được tạo
```

### Failure/fallback

- Provider timeout → error card → manual editor vẫn dùng được.
- Malformed structured output → không hiện proposal hợp lệ → manual fallback.
- Verifier rejection → lỗi xác định được → edit/retry/manual path.
- Proposal edit → version đổi → validation cũ không còn đủ để approve.
- Source data đổi → stale conflict → revalidate trước decision.
- Reject → không tạo business records.
- Approve retry → không tạo duplicate.
- Employee/direct unauthorized request → `403` và không rò dữ liệu.
- Cross-tenant resource reference → bị chặn ở API và PostgreSQL RLS.
- Prompt injection → không thay đổi permission, policy hoặc tool allowlist.

## 17. Bước phát triển kế tiếp

UX Spec này được hiệu chỉnh sau Task 8 để khôi phục contract conversation-first.
Task 9 cũ bị supersede. Bước kế tiếp là duyệt corrective design và implementation
plan cho conversation/message/turn persistence, bounded intent router, read-only
work tools và transcript UI trước khi tiếp tục Task 10 hoặc Phase 2 closure.
