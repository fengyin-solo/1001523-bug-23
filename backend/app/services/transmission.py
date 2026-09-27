"""数据传输业务规则：状态流转、字段校验与筛选口径都收在这里。

列表、概览看板、导出清单共用本模块里的同一套口径函数，
任何一处要调整统计规则都只改这里，避免三处数字对不上。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "transmission"
REQUIRED_FIELDS = ["链路编号", "所属站点", "传输方式"]
OPTIONAL_FIELDS = ["上报频次", "最近上报时刻", "缺报次数", "链路带宽"]
STATUS_ORDER = ["待开通", "正常上报", "缺报告警", "已停用"]
TERMINAL_STATUS = STATUS_ORDER[-1]  # 已停用：不计入待处理
ALARM_STATUS = "缺报告警"
ACTIVE_STATUS = "正常上报"

# 状态流转表：source 为允许执行动作的起始状态；目标状态幂等，重复执行不来回切换。
ACTION_TRANSITIONS: dict[str, dict[str, Any]] = {
    "开通链路": {"source": {"待开通"}, "target": ACTIVE_STATUS},
    "确认恢复": {"source": {ALARM_STATUS}, "target": ACTIVE_STATUS},
    "停用链路": {"source": {"待开通", ACTIVE_STATUS, ALARM_STATUS}, "target": TERMINAL_STATUS},
}


def is_pending(row: dict[str, Any]) -> bool:
    """待处理口径：未停用的链路都需要跟进，已停用一律不计入。"""
    return row.get("status") != TERMINAL_STATUS


def is_abnormal(row: dict[str, Any]) -> bool:
    """异常口径：处于缺报告警的链路计为异常。"""
    return row.get("status") == ALARM_STATUS


def missing_reports(row: dict[str, Any]) -> int | None:
    """读取缺报次数；缺失或不是数字时返回 None，由数据标记单独标出。"""
    value = row.get("缺报次数")
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def row_issues(row: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    """数据质量标记：链路编号重复、缺报次数缺失的链路要单独标出来。"""
    issues: list[str] = []
    code = str(row.get("链路编号") or "").strip()
    if code and sum(1 for item in rows if str(item.get("链路编号") or "").strip() == code) > 1:
        issues.append("链路编号重复")
    if missing_reports(row) is None:
        issues.append("缺报次数缺失")
    return issues


def overview_metrics(rows: list[dict[str, Any]]) -> dict[str, int]:
    """概览看板口径：与列表、导出共用 is_pending / is_abnormal。"""
    return {
        "pending": sum(1 for row in rows if is_pending(row)),
        "abnormal": sum(1 for row in rows if is_abnormal(row)),
    }


store.register_metrics(MODULE, overview_metrics)


class TransmissionService:
    def _shaped(self, row: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        """输出前统一塑形：状态标记按口径重算，并附上数据质量标记。"""
        item = dict(row)
        item["pending"] = is_pending(row)
        item["abnormal"] = is_abnormal(row)
        item["issues"] = row_issues(row, rows)
        return item

    def _sync_flags(self, entry: dict[str, Any]) -> None:
        """写回与口径一致的状态标记，保证落库数据不漂移。"""
        entry["pending"] = is_pending(entry)
        entry["abnormal"] = is_abnormal(entry)

    def summary(self) -> dict[str, int]:
        """模块级汇总：页脚待处理条数、统计卡片与概览看板保持同一份数字。"""
        rows = store.rows(MODULE)
        return {
            "在用链路": sum(1 for row in rows if row.get("status") == ACTIVE_STATUS),
            "缺报链路": sum(1 for row in rows if row.get("status") == ALARM_STATUS),
            "今日缺报次数": sum(count for row in rows if (count := missing_reports(row)) is not None),
            "待处理": sum(1 for row in rows if is_pending(row)),
            "数据标记": sum(1 for row in rows if row_issues(row, rows)),
        }

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("链路编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        all_rows = store.rows(MODULE)
        return [self._shaped(row, all_rows) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._shaped(entry, store.rows(MODULE))

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry.update({field: values[field] for field in OPTIONAL_FIELDS if values.get(field) is not None})
        entry["status"] = STATUS_ORDER[0]
        entry["链路状态"] = STATUS_ORDER[0]
        self._sync_flags(entry)
        rows.append(entry)
        return self._shaped(entry, rows), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"传输链路 {entry_id} 不存在或已归档"
        rule = ACTION_TRANSITIONS.get(action)
        if rule is None:
            return None, f"动作「{action}」不属于数据传输可执行范围"
        current = str(entry.get("status") or "")
        target = rule["target"]
        if current == target:
            return self._shaped(entry, store.rows(MODULE)), f"传输链路已处于「{target}」，无需重复{action}"
        if current not in rule["source"]:
            return None, f"传输链路当前为「{current}」，不能{action}"
        entry["status"] = target
        entry["链路状态"] = target
        if action in ("开通链路", "确认恢复"):
            # 链路恢复上报：缺报次数清零，最近上报时刻刷新为当前时间。
            entry["缺报次数"] = 0
            entry["最近上报时刻"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._sync_flags(entry)
        return self._shaped(entry, store.rows(MODULE)), f"传输链路已{action}"
