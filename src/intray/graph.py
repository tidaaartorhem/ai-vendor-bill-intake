"""InTray LangGraph state graph.

intake -> extract -> normalize -> dedupe -> validate -> split_detect
       -> route -> draft -> gate

Fully deterministic; no LLM calls. The split_detect node scans the whole
replay batch (carried in state) so cross-bill patterns are caught per bill.
"""

from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from . import nodes


class IntakeState(TypedDict, total=False):
    bill: Dict[str, Any]
    replay_date: str
    vendor_register: List[Dict[str, Any]]
    posted_register: List[Dict[str, Any]]
    fx: Dict[str, Any]
    batch_invoices: List[Dict[str, Any]]
    extracted: Dict[str, Any]
    alias: Dict[str, Any]
    vendor_id: Optional[str]
    vendor: Optional[Dict[str, Any]]
    total_cad: float
    batch_invoice: Dict[str, Any]
    dedupe: Dict[str, Any]
    flags: List[str]
    flag_details: List[Dict[str, Any]]
    split_info: Optional[Dict[str, Any]]
    split_scan: Dict[str, Any]
    tier: str
    action: str
    draft: str
    reasoning: str
    gate_decision: str
    gated: bool


def build_graph():
    g = StateGraph(IntakeState)
    g.add_node("intake", nodes.intake_node)
    g.add_node("extract", nodes.extract_node)
    g.add_node("normalize", nodes.normalize_node)
    g.add_node("dedupe", nodes.dedupe_node)
    g.add_node("validate", nodes.validate_node)
    g.add_node("split_detect", nodes.split_detect_node)
    g.add_node("route", nodes.route_node)
    g.add_node("draft", nodes.draft_node)
    g.add_node("gate", nodes.gate_node)
    g.set_entry_point("intake")
    g.add_edge("intake", "extract")
    g.add_edge("extract", "normalize")
    g.add_edge("normalize", "dedupe")
    g.add_edge("dedupe", "validate")
    g.add_edge("validate", "split_detect")
    g.add_edge("split_detect", "route")
    g.add_edge("route", "draft")
    g.add_edge("draft", "gate")
    g.add_edge("gate", END)
    return g.compile()
