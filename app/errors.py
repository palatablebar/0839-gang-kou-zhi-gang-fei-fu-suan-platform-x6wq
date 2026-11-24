from flask import jsonify


MESSAGES = {
    "EMPTY_FILE": "文件为空",
    "BLANK_FILE": "文件只有空白",
    "HEADER_ONLY": "文件只有表头",
    "HEADER_MISMATCH": "表头与本项目字段不一致",
    "UNCLOSED_QUOTE": "引号未闭合，文件已拒收",
    "TOO_MANY_ROWS": "数据行超过上限",
    "FILE_TOO_LARGE": "文件超过大小上限",
    "KEY_MISSING": "主键为空",
    "CONFLICT_DUPLICATE": "同一键存在冲突内容",
    "SAMPLE_UNKNOWN": "样例不存在",
    "STAGE_UNKNOWN": "阶段不存在",
    "RUN_NOT_FOUND": "批次不存在",
    "STALE_REVIEW": "批次已被更新，请刷新后复核",
    "GATE_BLOCKED": "存在阻断项，不能签发",
    "NOT_APPROVED": "批次尚未签发",
    "BAD_REQUEST": "请求内容不完整",
    "BAD_CLOSURE_DATE": "休港日期不是合法 ISO 日期",
    "BAD_CLOSURE_STATUS": "休港日期状态只能是 CONFIRMED 或 PENDING",
    "DOC_ID_MISSING": "补证缺少 doc_id，无法做幂等登记",
    "DOC_CONTENT_CONFLICT": "同一 doc_id 已登记且内容不一致，拒绝覆盖",
    "CLOSURES_EMPTY": "补证未携带任何休港日期",
    "CORRECTION_NOT_FOUND": "更正记录不存在",
    "CORRECTION_PENDING_HELD": "存在待核日期会改变免堆截止日或应收金额，先保留原账",
    "CORRECTION_UNBALANCED": "更正差额未通过累计守恒校验，已保留原账",
    "EVIDENCE_NOT_FOUND": "该证据版本不存在",
    "RUN_NO_BASE_ROWS": "批次缺少可复算的箱单",
}


class DomainIssue(Exception):
    def __init__(self, code: str, status: int = 400, detail: str | None = None):
        self.code = code
        self.status = status
        self.detail = detail
        super().__init__(code)


def error_response(exc: DomainIssue):
    return jsonify(error=exc.detail or MESSAGES.get(exc.code, "请求无法处理"), code=exc.code), exc.status
