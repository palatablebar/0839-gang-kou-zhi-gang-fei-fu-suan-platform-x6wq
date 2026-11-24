# 港口滞港费复算台

港口箱管结算员处理免堆日历与阶梯费率的本地工作台。样例、规则和复核记录都在项目内，不依赖外部服务。

## 启动

```bash
docker compose up --build
```

打开 `http://127.0.0.1:${PORT:-18520}`。默认端口见 `docker-compose.yml`。

## 验证

```bash
docker compose exec -T app pytest -q
docker compose config --quiet
```

## 操作

1. 在左侧选阶段，查看采信、整理、计算、判定和对账结果。
2. 选择 `dirty` 样例观察坏行和隔离原因。
3. 换 `clean` 样例执行批次，填写复核意见后签发。
4. 下载证据 JSON，核对来源摘要、指标和签发版本。
5. 批次签发后，在「休港补证复算更正」面板填写补证编号与休港日期（`CONFIRMED`/`PENDING`），
   先复算预览：待核日期会改变免堆截止日或应收的箱子保留原账，其余按增量入账；
   更正签发后旧凭证版本仍可原样下载，重跑同一补证不会重复记账。

业务规则见 `docs/BUSINESS-RULES.md`，字段定义见 `docs/DATA-DICTIONARY.md`，接口见 `docs/HTTP.md`。
