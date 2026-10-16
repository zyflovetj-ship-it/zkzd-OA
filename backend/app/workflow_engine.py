"""流程引擎核心（纯逻辑，不依赖数据库）：图遍历、条件路由、并行汇聚、会签策略。

图结构约定（WorkflowVersion.graph）：
{
  "nodes": [
    {"id":"start","type":"start","name":"发起"},
    {"id":"n1","type":"approval","name":"部门经理","assignee":{"type":"role","value":"manager"}},
    {"id":"n2","type":"countersign","name":"会签","assignees":[...],"strategy":"all","ratio":null},
    {"id":"c1","type":"condition","name":"金额分支","parallel":false},
    {"id":"j1","type":"join","name":"汇聚"},
    {"id":"nc","type":"notify","name":"抄送","assignees":[...]},
    {"id":"end","type":"end","name":"结束"}
  ],
  "edges": [
    {"id":"e1","source":"start","target":"n1"},
    {"id":"e3","source":"c1","target":"n2",
     "condition":{"op":"and","rules":[{"field":"amount","op":">","value":5000}]}}
  ]
}
节点类型：start / approval / countersign / condition / join / notify / end
"""
from typing import Any

AUTO_NODE_TYPES = {"start", "condition", "join"}
TERMINAL_TYPES = {"end"}


def index_graph(graph: dict) -> tuple[dict, dict, dict]:
    """返回 (nodes_by_id, edges_out_by_source, edges_in_by_target)。"""
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    out: dict[str, list[dict]] = {}
    inc: dict[str, list[dict]] = {}
    for e in graph.get("edges", []):
        out.setdefault(e["source"], []).append(e)
        inc.setdefault(e["target"], []).append(e)
    return nodes, out, inc


def _coerce(left: Any, right: Any) -> tuple[Any, Any]:
    """数值比较前尝试把两侧转成数字，失败则按原值比较。"""
    try:
        if isinstance(left, (int, float)) or isinstance(right, (int, float)):
            l = float(left) if left is not None and left != "" else None
            r = float(right) if right is not None and right != "" else None
            if l is not None and r is not None:
                return l, r
    except (TypeError, ValueError):
        pass
    return left, right


def eval_rule(rule: dict, form_data: dict) -> bool:
    """单条规则：{"field":"amount","op":">","value":5000}"""
    field = rule.get("field")
    left = (form_data or {}).get(field)
    right = rule.get("value")
    op = rule.get("op", "==")

    if op in ("in", "not_in"):
        values = right if isinstance(right, list) else [right]
        hit = left in values
        return hit if op == "in" else not hit
    if op == "contains":
        return right in (left or "")

    l, r = _coerce(left, right)
    try:
        if op == "==":
            return l == r
        if op == "!=":
            return l != r
        if op == ">":
            return l > r
        if op == ">=":
            return l >= r
        if op == "<":
            return l < r
        if op == "<=":
            return l <= r
    except TypeError:
        return False
    return False


def eval_condition(cond: dict | None, form_data: dict) -> bool:
    """条件组：{"op":"and"|"or","rules":[...]}，无条件视为通过（默认分支）。"""
    if not cond:
        return True
    rules = cond.get("rules", [])
    if not rules:
        return True
    results = [eval_rule(r, form_data) for r in rules]
    return all(results) if cond.get("op", "and") == "and" else any(results)


def is_join_ready(
    graph: dict, join_id: str, finished_nodes: set, activated_nodes: set
) -> bool:
    """汇聚节点就绪条件。

    关键语义：只等待「真正被激活过」的入边分支。若按全部入边来源判断，
    互斥分支下未激活的分支永远无法完成，会造成流程死锁。
    """
    _, _, inc = index_graph(graph)
    sources = {e["source"] for e in inc.get(join_id, [])}
    if not sources:
        return True
    relevant = {s for s in sources if s in activated_nodes}
    if not relevant:
        return True
    return relevant.issubset(finished_nodes)


def advance(
    graph: dict,
    from_node_id: str,
    form_data: dict,
    finished_nodes: set,
    activated_nodes: set | None = None,
) -> tuple[list[str], list[str]]:
    """从 from_node_id 推进流程。

    返回 (待激活节点 id 列表, 途经的自动节点 id 列表)。
    自动节点（start/condition/join）不产生任务，会就地展开；
    join 未就绪时静默等待，不激活任何节点。
    """
    nodes, out, _ = index_graph(graph)
    activated_nodes = set(activated_nodes or set())
    to_activate: list[str] = []
    passed: list[str] = []
    queue = [from_node_id]
    seen: set[str] = set()

    while queue:
        nid = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        node = nodes.get(nid)
        if not node:
            continue
        ntype = node.get("type", "approval")

        if ntype in TERMINAL_TYPES:
            to_activate.append(nid)
            continue

        edges = out.get(nid, [])
        if ntype == "condition":
            # 分支：parallel=true 时所有命中分支并行，否则取第一个命中（互斥）
            matched: list[dict] = []
            default_edge: dict | None = None
            for e in edges:
                cond = e.get("condition")
                if not cond:
                    if default_edge is None:
                        default_edge = e
                    continue
                if eval_condition(cond, form_data):
                    matched.append(e)
            chosen = (matched if node.get("parallel") else matched[:1]) or (
                [default_edge] if default_edge else []
            )
            targets = [e["target"] for e in chosen]
            passed.append(nid)
        else:
            targets = [e["target"] for e in edges]
            if ntype in AUTO_NODE_TYPES:
                passed.append(nid)

        for t in targets:
            tnode = nodes.get(t) or {}
            ttype = tnode.get("type", "approval")
            if ttype == "join":
                # 汇聚：已激活分支全部结束才继续，否则静默等待另一分支
                fin = finished_nodes | set(passed)
                act = activated_nodes | set(passed) | set(to_activate)
                if is_join_ready(graph, t, fin, act):
                    queue.append(t)
            elif ttype in TERMINAL_TYPES:
                to_activate.append(t)
            elif ttype in AUTO_NODE_TYPES:
                queue.append(t)
            else:
                to_activate.append(t)

    return to_activate, passed


def countersign_result(
    statuses: list[str], strategy: str = "all", ratio: float | None = None
) -> str | None:
    """会签节点结果：返回 approved / rejected / None（仍需等待）。"""
    if not statuses:
        return "approved"
    total = len(statuses)
    approved = sum(1 for s in statuses if s == "approved")
    rejected = sum(1 for s in statuses if s == "rejected")
    pending = total - approved - rejected

    if strategy == "any":
        if approved >= 1:
            return "approved"
        return None if pending else "rejected"
    if strategy == "ratio":
        need = ratio if ratio is not None else 1.0
        if approved / total >= need:
            return "approved"
        # 剩余票数已无法达标，提前判定驳回
        if approved + pending < need * total:
            return "rejected"
        return None if pending else "rejected"
    # 默认 all：全员同意才通过，任一驳回即驳回
    if rejected >= 1:
        return "rejected"
    return None if pending else "approved"
