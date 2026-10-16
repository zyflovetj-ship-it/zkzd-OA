"""建模引擎字段 schema 的纯逻辑测试（不依赖数据库，可直接 python3 运行）。

覆盖：字段定义校验（标识/重名/类型/选项）、取值转换（数字/金额/布尔/日期/选项/邮箱）、
必填拦截（显式空值与整字段缺失）、未知字段丢弃、过滤与模糊搜索。
运行：cd backend && python3 tests/test_model_fields.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.model_fields import (  # noqa: E402
    clean_data,
    coerce_value,
    normalize_fields,
    record_matches,
)

FAILED = []


def check(desc: str, cond: bool):
    print(("  PASS " if cond else "  FAIL ") + desc)
    if not cond:
        FAILED.append(desc)


def expect_error(desc: str, fn, keyword: str = ""):
    try:
        fn()
    except ValueError as exc:
        ok = keyword in str(exc) if keyword else True
        print(("  PASS " if ok else "  FAIL ") + f"{desc} -> {exc}")
        if not ok:
            FAILED.append(desc)
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL {desc} -> 抛出了非预期异常 {type(exc).__name__}: {exc}")
        FAILED.append(desc)
    else:
        print(f"  FAIL {desc} -> 未抛错")
        FAILED.append(desc)


print("== 字段定义校验 ==")
fields = normalize_fields(
    [
        {"key": "name", "label": "客户名称", "type": "text", "required": True},
        {"key": "amount", "label": "合同金额", "type": "money"},
        {"key": "signed", "label": "已签署", "type": "bool"},
        {"key": "level", "label": "等级", "type": "select", "options": ["A", "B", "C"]},
        {"key": "tags", "label": "标签", "type": "multiselect", "options": ["重点", "续约"]},
        {"key": "email", "label": "联系邮箱", "type": "email"},
        {"key": "sign_date", "label": "签署日期", "type": "date"},
    ]
)
check("正常 schema 通过并补齐默认值", len(fields) == 7 and fields[0]["unique"] is False)
check("select 字段保留选项", fields[3]["options"] == ["A", "B", "C"])

expect_error("非法标识（大写开头）", lambda: normalize_fields([{"key": "Name", "label": "x"}]))
expect_error("重复标识", lambda: normalize_fields(
    [{"key": "a", "label": "A"}, {"key": "a", "label": "B"}]), "重复")
expect_error("缺少名称", lambda: normalize_fields([{"key": "a", "label": "  "}]), "缺少中文名称")
expect_error("不支持的类型", lambda: normalize_fields(
    [{"key": "a", "label": "A", "type": "vector"}]), "类型不支持")
expect_error("选项类型缺选项", lambda: normalize_fields(
    [{"key": "level", "label": "等级", "type": "select"}]), "必须配置选项")
expect_error("非数组输入", lambda: normalize_fields("oops"), "格式错误")
check("None 输入视为空 schema", normalize_fields(None) == [])

print("== 取值转换 ==")
check("文本原样返回", coerce_value(fields[0], "中科智电") == "中科智电")
check("金额转两位小数", coerce_value(fields[1], "12000.566") == 12000.57)
check("布尔字符串 true", coerce_value(fields[2], "yes") is True)
check("布尔保留 False", coerce_value(fields[2], False) is False)
check("日期归一为 ISO", coerce_value(fields[6], "2026/09/25") == "2026-09-25")
check("选项命中返回原值", coerce_value(fields[3], "B") == "B")
check("多选返回列表", coerce_value(fields[4], ["重点"]) == ["重点"])
expect_error("选项越界", lambda: coerce_value(fields[3], "Z"), "取值不合法")
expect_error("邮箱缺 @", lambda: coerce_value(fields[5], "abc.com"), "取值不合法")
expect_error("金额传非数字", lambda: coerce_value(fields[1], "十二万"), "取值不合法")
expect_error("日期非法", lambda: coerce_value(fields[6], "昨天"), "取值不合法")
expect_error("必填字段显式传空", lambda: coerce_value(fields[0], "  "), "为必填项")

print("== 数据清洗 ==")
cleaned = clean_data(
    fields,
    {
        "name": "控赛集团",
        "amount": "88000",
        "signed": "true",
        "level": "A",
        "tags": ["重点", "续约"],
        "email": "a@b.com",
        "sign_date": "2026-09-25",
        "hacker": "<script>",  # 未定义字段必须丢弃
    },
)
check("未知字段被丢弃", "hacker" not in cleaned)
check("全部字段按类型转换", cleaned == {
    "name": "控赛集团", "amount": 88000.0, "signed": True, "level": "A",
    "tags": ["重点", "续约"], "email": "a@b.com", "sign_date": "2026-09-25",
})
check("缺失非必填补 None", clean_data(fields, {"name": "仅填必填"})["tags"] is None)
expect_error("必填字段整体缺失", lambda: clean_data(fields, {"amount": 1}), "为必填项")
check("局部更新不清零其它字段",
      clean_data(fields, {"level": "B"}, partial=True) == {"level": "B"})
expect_error("局部更新仍拒绝空的必填项",
             lambda: clean_data(fields, {"level": "B", "name": ""}, partial=True), "为必填项")

print("== 过滤与搜索 ==")
row = {"name": "控赛集团", "level": "A", "amount": 88000, "tags": ["重点"]}
check("等值命中", record_matches(row, filters={"level": "A"}))
check("等值未命中", not record_matches(row, filters={"level": "B"}))
check("列表任一命中", record_matches(row, filters={"level": ["A", "B"]}))
check("多条件需全部满足", not record_matches(row, filters={"level": "A", "amount": 1}))
check("模糊搜索大小写无关", record_matches(row, q="控赛"))
check("搜索命中数字", record_matches(row, q="88000"))
check("搜索未命中", not record_matches(row, q="不存在"))
check("空条件全部返回", record_matches(row) and record_matches({}, filters=None, q=None))

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} 项 ->", FAILED)
    sys.exit(1)
print("ALL PASSED")
