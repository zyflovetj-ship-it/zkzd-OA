"""建模引擎字段 schema：纯函数实现，不依赖框架，便于单测覆盖全部校验分支。

职责边界：
- 只做「schema 校验」与「取值转换 / 过滤」，不碰数据库、不碰 HTTP；
- 异常统一抛 ValueError（中文原因），由服务层映射为 422 ValidationError，
  这样 Clients 看到的仍是规范化错误结构，而本模块可被独立测试。
"""
import re
from datetime import date, datetime

FIELD_TYPES = {
    "text", "textarea", "number", "money", "date", "datetime", "bool",
    "select", "radio", "multiselect", "email",
}
OPTION_TYPES = {"select", "radio", "multiselect"}
_FIELD_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def normalize_fields(raw: list[dict] | None) -> list[dict]:
    """校验并规范化字段定义；非法 schema 一律 ValueError，绝不落库。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("字段定义格式错误")
    seen: set[str] = set()
    out: list[dict] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"第 {i + 1} 个字段格式错误")
        key = str(item.get("key", "")).strip()
        label = str(item.get("label", "")).strip()
        ftype = str(item.get("type", "text")).strip()
        if not _FIELD_KEY.match(key):
            raise ValueError(f"第 {i + 1} 个字段标识不合法（小写字母开头，可含数字与下划线）")
        if key in seen:
            raise ValueError(f"字段标识重复：{key}")
        seen.add(key)
        if not label:
            raise ValueError(f"字段 {key} 缺少中文名称")
        if ftype not in FIELD_TYPES:
            raise ValueError(f"字段 {key} 类型不支持：{ftype}")
        options = [str(o).strip() for o in (item.get("options") or []) if str(o).strip()]
        if ftype in OPTION_TYPES and not options:
            raise ValueError(f"字段 {key} 为 {ftype} 类型，必须配置选项")
        out.append(
            {
                "key": key,
                "label": label,
                "type": ftype,
                "required": bool(item.get("required", False)),
                "unique": bool(item.get("unique", False)),
                "options": options,
                "default": item.get("default", None),
            }
        )
    return out


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, list) and not value:
        return True
    return False


def coerce_value(field: dict, value):
    """按字段类型转换取值；失败抛 ValueError。

    约定：无论是否局部更新，显式给必填字段传空值一律拒绝；未传的字段走 clean_data 处理。
    """
    label = field["label"]
    if _is_empty(value):
        if field.get("required"):
            raise ValueError(f"{label} 为必填项")
        return None
    ftype = field["type"]
    try:
        if ftype in ("text", "textarea", "email"):
            text = str(value)
            if ftype == "email" and "@" not in text:
                raise ValueError
            return text
        if ftype in ("number", "money"):
            num = float(value)
            if ftype == "number" and float(num).is_integer():
                return int(num)
            return round(num, 2)
        if ftype == "bool":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("true", "1", "yes", "on")
        if ftype in ("date", "datetime"):
            if isinstance(value, (datetime, date)):
                return value.isoformat()
            text = str(value).strip().replace("/", "-")
            datetime.fromisoformat(text)  # 归一 ISO 串，跨 SQLite/PG 行为一致
            return text
        if ftype == "multiselect":
            raw = [str(v).strip() for v in value] if isinstance(value, list) else [str(value)]
            bad = [v for v in raw if v not in (field.get("options") or [])]
            if bad:
                raise ValueError
            return raw
        if ftype in OPTION_TYPES:
            picked = str(value).strip()
            if picked not in (field.get("options") or []):
                raise ValueError
            return picked
    except (TypeError, ValueError):
        raise ValueError(f"{label} 取值不合法")
    return None


def clean_data(fields: list[dict], payload: dict, *, partial: bool = False) -> dict:
    """按 schema 过滤与转换：未知字段丢弃，缺失字段补 None，必填缺失则报错。"""
    if not isinstance(payload, dict):
        raise ValueError("数据格式错误")
    specs = {f["key"]: f for f in fields}
    out: dict = {}
    for key, value in payload.items():
        spec = specs.get(key)
        if not spec:
            continue
        out[key] = coerce_value(spec, value)
    if not partial:
        for spec in fields:
            if spec["key"] in out:
                continue
            if spec.get("required"):
                raise ValueError(f"{spec['label']} 为必填项")
            out[spec["key"]] = None
    return out


def record_matches(data: dict, filters: dict | None = None, q: str | None = None) -> bool:
    """JSON 数据行的等值过滤 + 全字段模糊搜索（JSON 列无法做方言无关的谓词下推）。"""
    data = data or {}
    for key, value in (filters or {}).items():
        cell = data.get(key)
        if isinstance(value, list):
            if not any(str(v) in str(cell or "") for v in value):
                return False
            continue
        if str(cell or "") != str(value):
            return False
    if q:
        blob = " ".join(str(v) for v in data.values() if v is not None)
        if q.lower() not in blob.lower():
            return False
    return True
