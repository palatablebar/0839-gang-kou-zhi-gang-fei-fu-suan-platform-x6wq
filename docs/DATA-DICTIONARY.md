# 字段定义

| 字段 | 类型 | 说明 |
|---|---|---|
| `container_id` | text | 主键 |
| `gate_in` | date | 业务字段 |
| `gate_out` | date | 业务字段 |
| `free_days` | int | 业务字段 |
| `invoice_cents` | int | 业务字段 |

空字符串、`-`、`NA`、`null` 和 `未提供` 按空值处理。金额字段在整理层转为整数分或整数最小单位；日期按 ISO 日期解析；带时间的字段按本地时间解析。标识字段保持为文本，前导零不会被去除。

## 休港补证与更正字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `doc_id` | text | 补证编号，同编号重跑幂等，同号内容冲突拒收 |
| `closures[].date` | date | 休港日期，ISO `YYYY-MM-DD` |
| `closures[].status` | enum | `CONFIRMED` 已确认 / `PENDING` 待核 |
| `closures[].note` | text | 备注，可空 |
| `entries[].action` | enum | `BOOKED` 入账 / `HELD` 待核保留原账 / `UNCHANGED` 无变化 |
| `entries[].booking_delta_cents` | int | 本次记账增量（分），HELD 恒为 0 |
| `entries[].cumulative_delta_cents` | int | 该箱历次入账差额累计，须等于现账减原账 |
| `entries[].current_fee_cents` | int | 按已确认日历复算的当前应收 |
| `entries[].tentative_fee_cents` | int | 假设待核全部成立的上限应收，仅用于提示 |
| `summary.balanced` | bool | 累计守恒是否通过，不通过禁止签发 |
| `evidence.version` | int | 证据版本：首发为 1，每次更正签发递增 |
