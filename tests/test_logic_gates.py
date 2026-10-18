"""v1.6.8: AND / OR / NOR / NOT blocks on the node canvas."""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from core.nodegraph_eval import evaluate


def _graph(gate, inputs, count=None, invert=None):
    """Text sources -> gate -> If (then "YES" / else "NO") -> Output.
    ``inputs`` is a list of strings, one Text block per gate input; an
    entry of None leaves that socket unwired."""
    nodes = [
        {"id": "g", "type": gate,
         "values": {k: v for k, v in (("count", count),
                                       ("invert", invert)) if v}},
        {"id": "yes", "type": "text", "values": {"value": "YES"}},
        {"id": "no", "type": "text", "values": {"value": "NO"}},
        {"id": "if", "type": "if", "values": {}},
        {"id": "z_out", "type": "output", "values": {}},
    ]
    edges = [
        {"from": "g", "out": "out", "to": "if", "in": "cond"},
        {"from": "yes", "out": "out", "to": "if", "in": "then"},
        {"from": "no", "out": "out", "to": "if", "in": "else"},
        {"from": "if", "out": "out", "to": "z_out", "in": "in"},
    ]
    sockets = ["in"] if gate == "not" else list("abcdefghij")
    for i, value in enumerate(inputs):
        if value is None:
            continue
        nodes.append({"id": f"s{i}", "type": "text",
                      "values": {"value": value}})
        edges.append({"from": f"s{i}", "out": "out",
                      "to": "g", "in": sockets[i]})
    return {"nodes": nodes, "edges": edges}


def _run(gate, inputs, count=None, invert=None):
    return evaluate(_graph(gate, inputs, count, invert), {}).strip()


@pytest.mark.parametrize("a, b, want_and, want_or, want_nor", [
    ("1", "1", "YES", "YES", "NO"),
    ("1", "", "NO", "YES", "NO"),
    ("", "1", "NO", "YES", "NO"),
    ("", "", "NO", "NO", "YES"),
])
def test_two_input_truth_tables(a, b, want_and, want_or, want_nor):
    assert _run("and", [a, b]) == want_and
    assert _run("or", [a, b]) == want_or
    assert _run("nor", [a, b]) == want_nor


def test_not():
    assert _run("not", ["x"]) == "NO"
    assert _run("not", [""]) == "YES"
    assert _run("not", [None]) == "YES"     # nothing wired = false -> true


def test_unwired_sockets_do_not_count():
    # a spare socket must not turn an AND false
    assert _run("and", ["1", "1", None], count=3) == "YES"
    assert _run("nor", ["", None, None], count=3) == "YES"


def test_nothing_wired_is_false():
    # a freshly dropped NOR must not switch a line on by itself
    assert _run("nor", []) == "NO"
    assert _run("and", []) == "NO"


def test_more_inputs_via_count():
    many = ["1"] * 9 + [""]
    assert _run("and", many, count=10) == "NO"
    assert _run("or", many, count=10) == "YES"
    # sockets above "count" are ignored
    assert _run("and", many, count=9) == "YES"


def test_gates_can_be_chained():
    # NOT(AND(a, b)) == NAND
    graph = _graph("not", [])
    graph["nodes"].append({"id": "and", "type": "and", "values": {}})
    graph["nodes"] += [{"id": "a", "type": "text", "values": {"value": "1"}},
                       {"id": "b", "type": "text", "values": {"value": "1"}}]
    graph["edges"] += [
        {"from": "a", "out": "out", "to": "and", "in": "a"},
        {"from": "b", "out": "out", "to": "and", "in": "b"},
        {"from": "and", "out": "out", "to": "g", "in": "in"},
    ]
    assert evaluate(graph, {}).strip() == "NO"


@pytest.mark.parametrize("a, b", [("1", "1"), ("1", ""), ("", "1"), ("", "")])
def test_inverted_output(a, b):
    # AND inverted = NAND, OR inverted = NOR, NOR inverted = OR
    assert _run("and", [a, b], invert="inverted") == \
        ("NO" if _run("and", [a, b]) == "YES" else "YES")
    assert _run("or", [a, b], invert="inverted") == _run("nor", [a, b])
    assert _run("nor", [a, b], invert="inverted") == _run("or", [a, b])


def test_inverted_with_nothing_wired_stays_false():
    for gate in ("and", "or", "nor"):
        assert _run(gate, [], invert="inverted") == "NO"
