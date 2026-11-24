# 接口

- `GET /`：工作台。
- `GET /api/catalog`：阶段、字段和样例。
- `POST /api/stages/{stage}`：按阶段返回处理结果。
- `POST /api/runs`：执行完整批次并保存草稿。
- `GET /api/runs/{id}`：读取批次（含更正记录与证据版本清单）。
- `POST /api/runs/{id}/review`：签发或暂缓，提交 `decision`、`comment`、`expected_revision`。
- `GET /api/runs/{id}/evidence`：下载已签发证据（首发版本，原样固化）。
- `GET /api/examples/{profile}`：下载样例。
- `GET /healthz`：健康检查。

## 休港补证复算更正

- `POST /api/runs/{id}/corrections`：登记一份休港补证并返回复算计划。
  请求体：`{"doc_id": "SUP-001", "closures": [{"date": "2026-11-05", "status": "CONFIRMED", "note": "台风"}]}`。
  `status` 取 `CONFIRMED`（已确认，当天入账）或 `PENDING`（待核，只用于判断是否保留原账）。
  同一 `doc_id` 重跑幂等；同号但内容不同返回 `DOC_CONTENT_CONFLICT`。
- `GET /api/runs/{id}/corrections`：列出该批次的全部补证更正。
- `GET /api/runs/{id}/corrections/{correctionId}`：读取单份更正的逐箱计划。
- `POST /api/runs/{id}/corrections/{correctionId}/review`：更正签发或保留原账，
  提交 `decision`（`APPROVED`/`HELD`）、`comment`、`expected_revision`。
  存在待核保留箱（`CORRECTION_PENDING_HELD`）或累计守恒不通过（`CORRECTION_UNBALANCED`）时拒绝签发，旧版原样保留。
- `GET /api/runs/{id}/evidence/versions`：证据版本清单（首发为 version 1，每次更正签发追加一版）。
- `GET /api/runs/{id}/evidence/versions/{version}`：按版本原样下载证据，含稳定摘要 `artifact_sha256`。
