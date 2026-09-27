"""数据传输业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "transmission"
REQUIRED_FIELDS = ["链路编号", "所属站点", "传输方式"]
LIST_FIELDS = ["链路编号", "所属站点", "传输方式", "上报频次", "最近上报时刻", "缺报次数", "链路带宽"]
STATUS_ORDER = ["待开通", "正常上报", "缺报告警", "已停用"]
# 待处理口径：只有待开通、缺报告警需要跟进；正常上报与已停用一律不计入。
PENDING_STATUSES = {"待开通", "缺报告警"}
# 动作 -> (允许的源状态, 目标状态)。目标状态是幂等终点：重复执行同一动作保持原状，不会来回切换。
TRANSITIONS = {
    "开通链路": ({"待开通", "已停用"}, "正常上报"),
    "确认恢复": ({"缺报告警"}, "正常上报"),
    "停用链路": ({"待开通", "正常上报", "缺报告警"}, "已停用"),
}


def _missing_count(value: Any) -> int | None:
    """把缺报次数解析成非负整数；空值、非数字都按缺失处理。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        count = int(text)
    except ValueError:
        return None
    return count if count >= 0 else None


class TransmissionService:
    def __init__(self) -> None:
        # 启动时先校准一次，保证概览看板在首次列表请求之前就读到正确口径。
        self._sync_rows()

    def _sync_rows(self) -> None:
        """重算全部链路的派生字段：待处理、数据标记、异常标识。

        列表、概览看板、导出清单读的都是这份结果，保证三处口径一致。
        """
        rows = store.rows(MODULE)
        code_counts: dict[str, int] = {}
        for row in rows:
            code = str(row.get("链路编号") or "").strip()
            if code:
                code_counts[code] = code_counts.get(code, 0) + 1
        for row in rows:
            row["pending"] = str(row.get("status") or "") in PENDING_STATUSES
            flags: list[str] = []
            code = str(row.get("链路编号") or "").strip()
            if code and code_counts.get(code, 0) > 1:
                flags.append("链路编号重复")
            if _missing_count(row.get("缺报次数")) is None:
                flags.append("缺报次数缺失")
            row["flags"] = flags
            row["abnormal"] = bool(flags)

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        """对给定链路集合出一份汇总，列表页脚、统计卡片、导出清单共用。"""
        return {
            "total": len(rows),
            "pending": sum(1 for row in rows if row.get("pending")),
            "abnormal": sum(1 for row in rows if row.get("abnormal")),
            "active": sum(1 for row in rows if row.get("status") == "正常上报"),
            "alarming": sum(1 for row in rows if row.get("status") == "缺报告警"),
            "missing_reports": sum(
                count for row in rows if (count := _missing_count(row.get("缺报次数"))) is not None
            ),
        }

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        self._sync_rows()
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("链路编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        summary = self.summarize(rows)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total, summary

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in LIST_FIELDS:
            if field in values:
                entry[field] = values.get(field)
        entry.setdefault("缺报次数", 0)
        entry["status"] = STATUS_ORDER[0]
        entry["链路状态"] = STATUS_ORDER[0]
        rows.append(entry)
        self._sync_rows()
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"传输链路 {entry_id} 不存在或已归档"
        if action not in TRANSITIONS:
            return None, f"动作「{action}」不属于数据传输可执行范围"
        sources, target = TRANSITIONS[action]
        current = str(entry.get("status") or "")
        if current == target:
            return entry, f"传输链路已处于「{target}」，{action}未重复执行"
        if current not in sources:
            return None, f"传输链路当前为「{current}」，不能执行{action}"
        entry["status"] = target
        entry["链路状态"] = target
        if action == "确认恢复":
            # 恢复上报：缺报次数清零，最近上报时刻刷新为当前时间。
            entry["缺报次数"] = 0
            entry["最近上报时刻"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._sync_rows()
        return entry, f"传输链路已{action}"
