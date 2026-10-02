"""DigestFormatNode — GOV-C2-018 Government Policy Digest Agent.

Assembles the email-ready weekly digest and synthesizes cross-ministry
dependencies from the per-ministry summaries, regulatory changes, deadline
highlights, and operational-impact flags produced upstream.
"""

from typing import Any, ClassVar, Dict, List, Set

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.schemas.state import from_json, to_json
from src.services.output_gate import DEADLINE_SECTION_HEADING


class DigestFormatNode(FunctionNode):
    """Assemble the weekly policy digest.

    Produces the complete digest text plus the cross-ministry linkages it
    surfaces. The deadline section is written first and unconditionally — the
    output boundary checks for it, so the two are kept in step through the one
    shared heading constant rather than two copies of the same string.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        ministry_summaries = from_json(state.get("per_ministry_summaries"), {})
        regulatory_changes = from_json(state.get("regulatory_changes"), [])
        operational_flags = from_json(state.get("operational_flags"), [])
        deadline_highlights = from_json(state.get("deadline_highlights"), [])

        if not isinstance(ministry_summaries, dict):
            ministry_summaries = {}
        for name, value in (
            ("regulatory_changes", regulatory_changes),
            ("operational_flags", operational_flags),
            ("deadline_highlights", deadline_highlights),
        ):
            if not isinstance(value, list):
                return {
                    "status": AgentStatus.ERROR.value,
                    "error_log": [f"DigestFormatNode: {name} is not a list"],
                    # The runner surfaces `formatted_output or result` as `output`. A reason left only in
                    # error_log reaches no one: the terminal result carries just `status`, and get_output()
                    # does not copy error_log out of the graph -- the caller sees a blank spinner.
                    "formatted_output": "Request could not be completed. "
                    + (f"DigestFormatNode: {name} is not a list"),
                }

        period = state.get("reporting_period") or "今週"
        ministries = from_json(state.get("ministries"), None)
        if not isinstance(ministries, list) or not ministries:
            ministries = sorted(ministry_summaries.keys())

        dependencies = _synthesize_dependencies(regulatory_changes)

        digest = _assemble_digest(
            period=period,
            ministries=ministries,
            ministry_summaries=ministry_summaries,
            regulatory_changes=regulatory_changes,
            deadline_highlights=deadline_highlights,
            operational_flags=operational_flags,
            dependencies=dependencies,
        )

        emit_trace_event(
            "digest_assembled",
            {
                "ministries": ministries,
                "deadline_count": len(deadline_highlights),
                "dependency_count": len(dependencies),
                "digest_length": len(digest),
            },
            state,
        )

        return {
            "assembled_digest": digest,
            "cross_ministry_dependencies": to_json(dependencies),
            "status": AgentStatus.SUCCESS.value,
        }


def _synthesize_dependencies(regulatory_changes: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Identify cross-ministry dependencies from shared regulatory areas."""
    area_map: Dict[str, Set[str]] = {}
    shared_keywords = ("事業者", "申請", "提出", "施行")
    for change in regulatory_changes:
        ministry = change.get("ministry", "")
        title = change.get("change", "")
        for keyword in shared_keywords:
            if keyword in title:
                area_map.setdefault(keyword, set()).add(ministry)

    dependencies: List[Dict[str, Any]] = []
    for area, ministries in area_map.items():
        if len(ministries) > 1:
            dependencies.append(
                {
                    "dependency": f"複数省庁で「{area}」関連の規制変更あり",
                    "ministries": sorted(ministries),
                }
            )
    return dependencies


def _assemble_digest(
    period: str,
    ministries: List[str],
    ministry_summaries: Dict[str, str],
    regulatory_changes: List[Dict[str, str]],
    deadline_highlights: List[Dict[str, str]],
    operational_flags: List[Dict[str, Any]],
    dependencies: List[Dict[str, Any]],
) -> str:
    """Assemble the weekly digest in markdown."""
    lines = [
        f"# 政策文書週次ダイジェスト — {period}",
        "",
        f"対象省庁: {', '.join(ministries)}",
        "",
        f"## {DEADLINE_SECTION_HEADING}",
        "",
    ]

    if deadline_highlights:
        for highlight in deadline_highlights:
            lines.append(f"- **{highlight.get('effective_date', '日付不明')}**: {highlight.get('change', '')}")
            lines.append(f"  → 必要な対応: {highlight.get('required_action', '')}")
    else:
        lines.append("- 今週の期限変更なし")
    lines.append("")

    lines.append("## 省庁別サマリー")
    lines.append("")
    for ministry in ministries:
        lines.append(f"### {ministry}")
        lines.append(ministry_summaries.get(ministry, "今週の更新なし"))
        lines.append("")

    if regulatory_changes:
        lines.append("## 主要規制変更")
        lines.append("")
        for change in regulatory_changes:
            lines.append(
                f"- [{change.get('ministry', '')}] {change.get('change', '')} "
                f"(施行日: {change.get('effective_date', '未定')}) — {change.get('impact', '')}"
            )
        lines.append("")

    if dependencies:
        lines.append("## 省庁横断依存関係")
        lines.append("")
        for dependency in dependencies:
            listed = " / ".join(str(name) for name in dependency.get("ministries", []))
            lines.append(f"- {dependency.get('dependency', '')} ({listed})")
        lines.append("")

    if operational_flags:
        lines.append("## 運用インパクトフラグ")
        lines.append("")
        for flag in operational_flags:
            listed = ", ".join(str(name) for name in flag.get("ministries", []))
            lines.append(f"- [{flag.get('flag', '')}] {flag.get('description', '')} ({listed})")
        lines.append("")

    return "\n".join(lines)
