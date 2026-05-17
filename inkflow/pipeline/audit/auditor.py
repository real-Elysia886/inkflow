"""Dual-Layer Auditor - Combines code-level checks with LLM evaluation.

Layer 1: Code checks (zero token) - deterministic rule validation
Layer 2: LLM evaluation - creative quality assessment (same as before)

The code check results are injected into the LLM prompt as known facts,
reducing the LLM's reasoning burden and improving consistency.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from inkflow.memory.world_state import WorldState
from inkflow.pipeline.audit.code_checks import CodeChecker, CodeCheckResult, CheckIssue
from inkflow.pipeline.quality import QualityScorer


@dataclass
class AuditReport:
    """Combined audit result from both layers."""
    # Code layer results
    code_result: CodeCheckResult = field(default_factory=CodeCheckResult)

    # LLM layer results (same structure as old QualityScorer output)
    llm_evaluation: Dict[str, Any] = field(default_factory=dict)

    # Combined verdict
    passed: bool = True
    critical_issues: List[CheckIssue] = field(default_factory=list)
    warning_issues: List[CheckIssue] = field(default_factory=list)
    auto_fixable_issues: List[CheckIssue] = field(default_factory=list)

    # Scores
    code_pass_rate: float = 1.0
    llm_total_score: int = 0
    anti_ai_score: int = 100

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage in chapter output."""
        llm = self.llm_evaluation or {}
        return {
            "passed": self.passed,
            "total_score": self.llm_total_score,
            "code_pass_rate": round(self.code_pass_rate, 2),
            "llm_total_score": self.llm_total_score,
            "anti_ai_score": self.anti_ai_score,
            # Flatten LLM evaluation fields to top level for frontend compat
            "issues": llm.get("issues", []),
            "highlights": llm.get("highlights", []),
            "rewrite_instructions": llm.get("rewrite_instructions", ""),
            # Dual-layer specific fields
            "critical_count": len(self.critical_issues),
            "warning_count": len(self.warning_issues),
            "auto_fixable_count": len(self.auto_fixable_issues),
            "critical_issues": [
                {
                    "category": i.category,
                    "dimension": i.dimension,
                    "description": i.description,
                    "suggestion": i.suggestion,
                    "auto_fixable": i.auto_fixable,
                }
                for i in self.critical_issues
            ],
            "warning_issues": [
                {
                    "category": i.category,
                    "dimension": i.dimension,
                    "description": i.description,
                    "suggestion": i.suggestion,
                }
                for i in self.warning_issues[:10]
            ],
            "llm_evaluation": llm,
            "code_checks_summary": {
                "total": self.code_result.checks_total,
                "passed": self.code_result.checks_passed,
                "failed": self.code_result.checks_failed,
            },
        }

    @property
    def rewrite_instructions(self) -> str:
        """Build rewrite instructions from critical and auto-fixable issues."""
        instructions = []
        for issue in self.critical_issues:
            instructions.append(f"[严重] {issue.description} → {issue.suggestion}")
        for issue in self.auto_fixable_issues:
            if issue.severity != "critical":  # avoid duplicates
                instructions.append(f"[需修复] {issue.description} → {issue.suggestion}")
        # Add LLM rewrite instructions if available
        llm_rewrite = self.llm_evaluation.get("rewrite_instructions", "")
        if llm_rewrite:
            instructions.append(f"[编辑建议] {llm_rewrite}")
        return "\n".join(instructions)


class DualLayerAuditor:
    """Combines code-level checks and LLM evaluation into a unified audit."""

    def __init__(self, quality_scorer: Optional[QualityScorer] = None,
                 role_name: str = "editor"):
        self.code_checker = CodeChecker()
        self.quality_scorer = quality_scorer or QualityScorer(role_name=role_name)

    def audit(self, chapter_text: str, outline: str,
              world_state: WorldState, chapter_number: int,
              anti_ai_score: int = 100) -> AuditReport:
        """Run dual-layer audit.

        Args:
            chapter_text: The chapter text to audit.
            outline: Chapter outline/goal.
            world_state: Current world state.
            chapter_number: Current chapter number.
            anti_ai_score: Pre-computed anti-AI score (avoids re-computation).

        Returns:
            AuditReport with combined results.
        """
        report = AuditReport()

        # ── Layer 1: Code checks (zero token) ──
        code_result = self.code_checker.check_all(chapter_text, world_state, chapter_number)
        report.code_result = code_result
        report.code_pass_rate = code_result.pass_rate

        # ── Layer 1.5: LLM verification of suspects (minimal token) ──
        suspects = [i for i in code_result.issues if i.evidence]
        if suspects:
            verdicts = self._verify_suspects(suspects, world_state)
            # Remove confirmed false positives
            code_result.issues = [
                i for i in code_result.issues
                if i not in suspects or verdicts.get(id(i)) != "false_positive"
            ]
            # Recalculate pass rate
            code_result.checks_failed = sum(1 for i in code_result.issues if i.severity in ("critical", "warning"))

        # Categorize issues
        for issue in code_result.issues:
            if issue.severity == "critical":
                report.critical_issues.append(issue)
            elif issue.severity == "warning":
                report.warning_issues.append(issue)
            if issue.auto_fixable:
                report.auto_fixable_issues.append(issue)

        # ── Layer 2: LLM evaluation ──
        # Build code check context to inject into LLM prompt
        code_context = self._build_code_context(code_result)

        llm_eval = self.quality_scorer.evaluate_with_code_context(
            chapter_text, outline, world_state, code_context
        )
        report.llm_evaluation = llm_eval
        report.llm_total_score = llm_eval.get("total_score", 0)
        report.anti_ai_score = anti_ai_score

        # ── Combined verdict ──
        # Critical code issues = fail regardless of LLM score
        # LLM pass threshold + anti-AI threshold also apply
        llm_pass = llm_eval.get("pass", False)
        anti_ai_pass = anti_ai_score >= 60
        no_critical = not code_result.has_critical

        report.passed = no_critical and llm_pass and anti_ai_pass

        return report

    def _build_code_context(self, code_result: CodeCheckResult) -> str:
        """Format code check results as context for the LLM prompt.

        This tells the LLM what issues have already been detected,
        so it can focus on creative quality rather than factual consistency.
        """
        if not code_result.issues:
            return "代码层检查全部通过，无事实性错误。"

        lines = ["代码层已检测到以下问题（请在评估时参考）："]
        for issue in code_result.issues:
            severity_label = {"critical": "严重", "warning": "警告", "info": "提示"}.get(issue.severity, "提示")
            lines.append(f"- [{severity_label}] {issue.dimension}: {issue.description}")

        # Add summary stats
        lines.append(f"\n总计：{code_result.checks_passed}/{code_result.checks_total} 项检查通过")
        if code_result.has_critical:
            lines.append(f"⚠ 有 {code_result.critical_count} 个严重问题需要修复")

        return "\n".join(lines)

    def _verify_suspects(self, suspects: List[CheckIssue],
                         world_state: WorldState) -> Dict[int, str]:
        """Verify suspect issues using a single batched LLM call.

        Returns a dict mapping issue id -> "false_positive" | "true_positive".
        """
        from inkflow.utils.llm_utils import call_llm, parse_json_response

        if not suspects:
            return {}

        # Build character status context
        char_statuses = []
        for name, char in world_state.characters.items():
            if char.status in ("dead", "missing"):
                char_statuses.append(f"- {name}: {char.status} ({char.description})")

        # Build suspect list
        suspect_lines = []
        for i, issue in enumerate(suspects):
            suspect_lines.append(f"[{i}] 角色: {issue.description[:20]}\n上下文: {issue.evidence[:300]}")

        prompt = f"""你是小说审校助手。请判断以下句子中，已故/失踪角色是否在"主动行动"而非"被提及"。

## 角色状态
{chr(10).join(char_statuses)}

## 待检查的句子
{chr(10).join(suspect_lines)}

对于每个句子，判断：
- "false_positive": 该角色只是被提及（对话中提到、回忆、叙述已发生的事等）
- "true_positive": 该角色确实在当前场景中主动行动（不应该发生）

输出JSON：
{{"verdicts": [{{"index": 0, "verdict": "false_positive"|"true_positive", "reason": "简要原因"}}]}}"""

        try:
            raw = call_llm(prompt, role_name=self.quality_scorer.role_name, temperature=0.1, json_mode=True)
            result = parse_json_response(raw)
            verdicts = {}
            for v in result.get("verdicts", []):
                idx = v.get("index", 0)
                if 0 <= idx < len(suspects):
                    verdicts[id(suspects[idx])] = v.get("verdict", "true_positive")
            return verdicts
        except Exception:
            # On failure, treat all as true_positive (conservative)
            return {id(s): "true_positive" for s in suspects}
