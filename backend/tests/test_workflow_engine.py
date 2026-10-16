"""流程引擎核心的纯逻辑测试（不依赖数据库，可直接 python3 运行）。

覆盖：条件求值、串行流转、互斥分支、并行分支、汇聚(join)防死锁、会签策略。
运行：cd backend && python3 tests/test_workflow_engine.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.workflow_engine import (  # noqa: E402
    advance,
    countersign_result,
    eval_condition,
    eval_rule,
    index_graph,
    is_join_ready,
)

FAILED = []


def check(name, actual, expected):
    ok = actual == expected
    print(f"{'PASS' if ok else 'FAIL'} | {name}\n      得到={actual} 期望={expected}")
    if not ok:
        FAILED.append(name)


# ---------- 1. 条件求值 ----------
def test_condition():
    fd = {"amount": 8000, "type": "采购", "days": 3}
    check("规则 amount>5000", eval_rule({"field": "amount", "op": ">", "value": 5000}, fd), True)
    check("规则 amount<=5000", eval_rule({"field": "amount", "op": "<=", "value": 5000}, fd), False)
    check("规则 type==采购", eval_rule({"field": "type", "op": "==", "value": "采购"}, fd), True)
    check("规则 type in 列表", eval_rule({"field": "type", "op": "in", "value": ["采购", "报销"]}, fd), True)
    check(
        "and 组合(全真)",
        eval_condition(
            {"op": "and", "rules": [
                {"field": "amount", "op": ">", "value": 5000},
                {"field": "days", "op": "<", "value": 5},
            ]},
            fd,
        ),
        True,
    )
    check(
        "and 组合(一假)",
        eval_condition(
            {"op": "and", "rules": [
                {"field": "amount", "op": ">", "value": 9000},
                {"field": "days", "op": "<", "value": 5},
            ]},
            fd,
        ),
        False,
    )
    check(
        "or 组合(一真)",
        eval_condition(
            {"op": "or", "rules": [
                {"field": "amount", "op": ">", "value": 9000},
                {"field": "days", "op": "<", "value": 5},
            ]},
            fd,
        ),
        True,
    )
    # 字符串数字也能正确数值比较
    check("字符串数字比较", eval_rule({"field": "amount", "op": ">", "value": "5000"}, fd), True)


# ---------- 2. 串行流转 ----------
SERIAL = {
    "nodes": [
        {"id": "start", "type": "start", "name": "发起"},
        {"id": "n1", "type": "approval", "name": "部门经理"},
        {"id": "n2", "type": "approval", "name": "总经理"},
        {"id": "end", "type": "end", "name": "结束"},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "n1"},
        {"id": "e2", "source": "n1", "target": "n2"},
        {"id": "e3", "source": "n2", "target": "end"},
    ],
}


def test_serial():
    act, passed = advance(SERIAL, "start", {}, set(), set())
    check("串行: 发起后激活 n1", act, ["n1"])
    check("串行: start 为自动节点已通过", passed, ["start"])

    act, passed = advance(SERIAL, "n1", {}, {"start"}, {"start", "n1"})
    check("串行: n1 通过后激活 n2", act, ["n2"])

    act, _ = advance(SERIAL, "n2", {}, {"start", "n1"}, {"start", "n1", "n2"})
    check("串行: n2 通过后到达结束", act, ["end"])


# ---------- 3. 互斥分支 + 汇聚（防死锁核心用例） ----------
BRANCH = {
    "nodes": [
        {"id": "start", "type": "start"},
        {"id": "c1", "type": "condition", "name": "金额判断"},
        {"id": "n_big", "type": "approval", "name": "总经理审批"},
        {"id": "n_small", "type": "approval", "name": "主管审批"},
        {"id": "j1", "type": "join", "name": "汇聚"},
        {"id": "end", "type": "end"},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "c1"},
        {"id": "e2", "source": "c1", "target": "n_big",
         "condition": {"op": "and", "rules": [{"field": "amount", "op": ">", "value": 5000}]}},
        {"id": "e3", "source": "c1", "target": "n_small"},  # 默认分支
        {"id": "e4", "source": "n_big", "target": "j1"},
        {"id": "e5", "source": "n_small", "target": "j1"},
        {"id": "e6", "source": "j1", "target": "end"},
    ],
}


def test_exclusive_branch():
    fd_big = {"amount": 8000}
    act, passed = advance(BRANCH, "start", fd_big, set(), set())
    check("互斥分支: 大额走总经理", act, ["n_big"])

    fd_small = {"amount": 1000}
    act, _ = advance(BRANCH, "start", fd_small, set(), set())
    check("互斥分支: 小额走默认分支主管", act, ["n_small"])

    # 关键：只激活了 n_big，汇聚不能等待从未激活的 n_small
    fin = {"start", "c1", "n_big"}
    act_nodes = {"start", "c1", "n_big"}
    act, passed = advance(BRANCH, "n_big", fd_big, fin, act_nodes)
    check("互斥分支: 汇聚后到达结束(不死锁)", act, ["end"])
    check("互斥分支: join 为途经自动节点", passed, ["j1"])


def test_join_waits_when_not_ready():
    # 并行场景下另一分支尚未完成，汇聚必须等待
    _, _, inc = index_graph(BRANCH)
    check("汇聚入边来源", sorted({e["source"] for e in inc["j1"]}), ["n_big", "n_small"])
    ready = is_join_ready(BRANCH, "j1", {"start", "c1", "n_big"}, {"start", "c1", "n_big", "n_small"})
    check("汇聚: 另一分支未完成时等待", ready, False)
    ready = is_join_ready(BRANCH, "j1", {"start", "c1", "n_big", "n_small"},
                          {"start", "c1", "n_big", "n_small"})
    check("汇聚: 两分支均完成则就绪", ready, True)


# ---------- 4. 并行分支 ----------
PARALLEL = {
    "nodes": [
        {"id": "start", "type": "start"},
        {"id": "c1", "type": "condition", "parallel": True, "name": "并行分发"},
        {"id": "n_a", "type": "approval", "name": "财务"},
        {"id": "n_b", "type": "approval", "name": "法务"},
        {"id": "j1", "type": "join"},
        {"id": "end", "type": "end"},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "c1"},
        {"id": "e2", "source": "c1", "target": "n_a",
         "condition": {"op": "and", "rules": [{"field": "amount", "op": ">", "value": 1000}]}},
        {"id": "e3", "source": "c1", "target": "n_b",
         "condition": {"op": "and", "rules": [{"field": "amount", "op": ">", "value": 100}]}},
        {"id": "e4", "source": "n_a", "target": "j1"},
        {"id": "e5", "source": "n_b", "target": "j1"},
        {"id": "e6", "source": "j1", "target": "end"},
    ],
}


def test_parallel():
    fd = {"amount": 8000}
    act, _ = advance(PARALLEL, "start", fd, set(), set())
    check("并行: 同时激活财务与法务", sorted(act), ["n_a", "n_b"])

    # 仅 n_a 完成，汇聚应继续等待 n_b
    act, _ = advance(PARALLEL, "n_a", fd, {"start", "c1", "n_a"},
                     {"start", "c1", "n_a", "n_b"})
    check("并行: 仅一支完成时汇聚等待", act, [])

    act, _ = advance(PARALLEL, "n_b", fd, {"start", "c1", "n_a", "n_b"},
                     {"start", "c1", "n_a", "n_b"})
    check("并行: 两支均完成后到达结束", act, ["end"])


# ---------- 5. 会签策略 ----------
def test_countersign():
    check("会签 all 全员同意", countersign_result(["approved", "approved"], "all"), "approved")
    check("会签 all 有人未决", countersign_result(["approved", "pending"], "all"), None)
    check("会签 all 任一驳回", countersign_result(["approved", "rejected"], "all"), "rejected")

    check("会签 any 一人同意即过", countersign_result(["approved", "pending"], "any"), "approved")
    check("会签 any 全驳回", countersign_result(["rejected", "rejected"], "any"), "rejected")
    check("会签 any 有人反对但他人未决", countersign_result(["rejected", "pending"], "any"), None)

    check("会签 ratio 达比例即过", countersign_result(["approved", "pending"], "ratio", 0.5), "approved")
    check(
        "会签 ratio 无法达标提前驳回",
        countersign_result(["approved", "rejected", "rejected"], "ratio", 0.6),
        "rejected",
    )
    check(
        "会签 ratio 仍有希望则等待",
        countersign_result(["approved", "rejected", "pending"], "ratio", 0.6),
        None,
    )


if __name__ == "__main__":
    test_condition()
    test_serial()
    test_exclusive_branch()
    test_join_waits_when_not_ready()
    test_parallel()
    test_countersign()
    print("\n" + "=" * 46)
    if FAILED:
        print(f"失败 {len(FAILED)} 项: {', '.join(FAILED)}")
        sys.exit(1)
    print("全部通过")
