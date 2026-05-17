"""Code-level deterministic checks for chapter auditing.

These checks run against WorldState data and chapter text using pure code logic.
Zero LLM token consumption. Each check returns a structured result with:
- pass/fail status
- severity (critical/warning/info)
- description of the issue
- suggested fix (if applicable)

Check categories:
1. Character status consistency
2. Resource continuity
3. Foreshadowing lifecycle
4. Information boundary violations
5. Timeline consistency
6. Subplot stagnation
7. Dialogue/narration ratio
8. Word count compliance
9. Fatigue word / banned pattern detection
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

from inkflow.memory.world_state import WorldState
from inkflow.pipeline.anti_ai import check_fatigue_words, check_banned_patterns, check_dialogue_ratio


@dataclass
class CheckIssue:
    """A single audit issue found by code-level checks."""
    category: str          # e.g. "character_status", "resource", "foreshadowing"
    severity: str          # "critical" | "warning" | "info"
    dimension: str         # human-readable dimension name
    description: str       # what went wrong
    suggestion: str = ""   # how to fix it
    auto_fixable: bool = False  # whether a reviser can auto-fix this
    evidence: str = ""     # matched text for LLM verification


@dataclass
class CodeCheckResult:
    """Aggregated result of all code-level checks."""
    issues: List[CheckIssue] = field(default_factory=list)
    checks_passed: int = 0
    checks_failed: int = 0
    checks_total: int = 0

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def pass_rate(self) -> float:
        if self.checks_total == 0:
            return 1.0
        return self.checks_passed / self.checks_total

    @property
    def has_critical(self) -> bool:
        return self.critical_count > 0


class CodeChecker:
    """Runs deterministic code-level checks against chapter text and WorldState."""

    def check_all(self, chapter_text: str, world_state: WorldState,
                  chapter_number: int) -> CodeCheckResult:
        """Run all code-level checks and return aggregated result."""
        result = CodeCheckResult()

        self._check_character_status(chapter_text, world_state, result)
        self._check_resource_continuity(chapter_text, world_state, result)
        self._check_foreshadowing_lifecycle(chapter_text, world_state, chapter_number, result)
        self._check_information_boundaries(chapter_text, world_state, result)
        self._check_timeline_consistency(chapter_text, world_state, result)
        self._check_subplot_stagnation(world_state, chapter_number, result)
        self._check_dialogue_ratio(chapter_text, result)
        self._check_word_count(chapter_text, result)
        self._check_anti_ai(chapter_text, result)

        return result

    def _check_character_status(self, text: str, ws: WorldState, result: CodeCheckResult):
        """Dead/missing characters should not appear as active participants.

        Uses proximity-based regex matching with dialogue exclusion.
        Stores evidence for LLM verification in DualLayerAuditor.
        """
        result.checks_total += 1
        issues = []

        # Split text into sentences
        sentences = re.split(r'[。！？\n]', text)

        # Flashback/narration exclusion markers
        flashback_markers = ['回忆', '想起', '当年', '曾经', '过去', '那时', '当年', '记得']

        for name, char in ws.characters.items():
            if char.status not in ("dead", "missing"):
                continue
            if name not in text:
                continue

            # Action verbs
            verbs = '说|道|笑|喊|走|跑|看|拿|站|坐|点头|摇头|开口|转身|挥|踢|打|杀|攻击|握|拔|挡|闪|跳|扑|冲'

            for sentence in sentences:
                if name not in sentence:
                    continue

                # Skip if sentence is inside dialogue (contains quotes around the name)
                # Simple heuristic: if the name appears between quotes, it's a mention
                if self._is_in_dialogue(sentence, name):
                    continue

                # Skip if flashback marker present
                if any(marker in sentence for marker in flashback_markers):
                    continue

                # Proximity check: verb within 15 chars of name
                pattern = rf'{re.escape(name)}.{{0,15}}?({verbs})'
                match = re.search(pattern, sentence)
                if match:
                    # Get surrounding context (100 chars before + after)
                    idx = text.find(sentence)
                    ctx_start = max(0, idx - 100)
                    ctx_end = min(len(text), idx + len(sentence) + 100)
                    context = text[ctx_start:ctx_end]

                    issues.append(CheckIssue(
                        category="character_status",
                        severity="critical",
                        dimension="角色状态一致性",
                        description=f"角色「{name}」状态为 {char.status}，但疑似有主动行为",
                        suggestion=f"确认「{name}」是否真的在行动，或修改其状态",
                        auto_fixable=False,
                        evidence=context,
                    ))
                    break  # One issue per character is enough

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    def _is_in_dialogue(self, sentence: str, name: str) -> bool:
        """Check if the character name appears primarily within dialogue."""
        # Find all quoted segments
        quotes = re.findall(r'[""「」『』](.*?)[""「」『』]', sentence)
        for q in quotes:
            if name in q:
                # Check if the name is ONLY in dialogue (not also in narration)
                non_dialogue = sentence
                for q2 in quotes:
                    non_dialogue = non_dialogue.replace(q2, '')
                if name not in non_dialogue:
                    return True
        return False

    def _check_resource_continuity(self, text: str, ws: WorldState, result: CodeCheckResult):
        """Lost/consumed resources should not reappear without acquisition."""
        result.checks_total += 1
        issues = []

        # Find resource names mentioned in text
        mentioned_resources = []
        for key, entry in ws.resource_ledger.entries.items():
            if entry.status in ("lost", "consumed", "destroyed") and entry.name in text:
                mentioned_resources.append(entry)

        for entry in mentioned_resources:
            # Check if there's a new acquisition context
            acquire_patterns = [
                rf'获得|得到|拿到|捡到|买入|收到.*{re.escape(entry.name)}',
                rf'{re.escape(entry.name)}.*出现|浮现',
            ]
            acquired = any(re.search(p, text) for p in acquire_patterns)
            if not acquired:
                issues.append(CheckIssue(
                    category="resource",
                    severity="critical",
                    dimension="资源连续性",
                    description=f"资源「{entry.name}」(owner: {entry.owner}) 已 {entry.status}，但本章再次出现",
                    suggestion=f"补充获得「{entry.name}」的情节，或移除相关描写",
                    auto_fixable=True,
                ))

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    def _check_foreshadowing_lifecycle(self, text: str, ws: WorldState,
                                        chapter_number: int, result: CodeCheckResult):
        """Resolved foreshadowing should not be re-planted; stale foreshadowing flagged."""
        result.checks_total += 1
        issues = []

        # Check for stale foreshadowing (pending for too long)
        stale = ws.get_stale_foreshadowing(max_age=15)
        for fs in stale:
            age = chapter_number - fs.planted_chapter
            issues.append(CheckIssue(
                category="foreshadowing",
                severity="warning",
                dimension="伏笔生命周期",
                description=f"伏笔「{fs.detail[:30]}...」已埋设 {age} 章仍未回收",
                suggestion="考虑在近期章节中回收此伏笔，或标记为无效",
            ))

        # Check for already-resolved foreshadowing being re-planted
        # Use character/resource names from the foreshadowing detail as keywords
        # instead of fragile first-10-chars matching
        resolved_details = [fs.detail for fs in ws.foreshadowing_pool if fs.status == "resolved"]
        known_names = set(ws.characters.keys()) | {e.name for e in ws.resource_ledger.entries.values()}
        for detail in resolved_details:
            # Extract entity names mentioned in the foreshadowing detail
            matched_names = [n for n in known_names if n in detail]
            for name in matched_names:
                if name in text:
                    # Check if this name appears in a foreshadowing-like context
                    fs_patterns = [
                        rf'{re.escape(name)}[^。！？]{{0,30}}(秘密|真相|隐藏|谜|线索)',
                        rf'(秘密|真相|隐藏|谜|线索)[^。！？]{{0,30}}{re.escape(name)}',
                    ]
                    if any(re.search(p, text) for p in fs_patterns):
                        issues.append(CheckIssue(
                            category="foreshadowing",
                            severity="warning",
                            dimension="伏笔生命周期",
                            description=f"已回收伏笔涉及的实体「{name}」在本章再次出现在伏笔语境中",
                            suggestion="确认是否为新伏笔，避免与已回收伏笔混淆",
                        ))
                        break  # One issue per resolved foreshadowing

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    def _check_information_boundaries(self, text: str, ws: WorldState, result: CodeCheckResult):
        """Characters should not know things they haven't learned.

        Uses the CharacterMatrix info_boundaries to detect potential violations.
        Stores evidence for LLM verification in DualLayerAuditor.
        """
        result.checks_total += 1
        issues = []

        # Get all known facts and who knows them
        boundaries = ws.character_matrix.info_boundaries
        if not boundaries:
            result.checks_passed += 1
            return

        # Build a map: fact -> set of characters who know it
        fact_knowers = {}
        for char_name, boundary in boundaries.items():
            for fact in boundary.known_facts:
                if fact not in fact_knowers:
                    fact_knowers[fact] = set()
                fact_knowers[fact].add(char_name)

        # Check if any character appears in text alongside a fact they don't know
        for char_name, boundary in boundaries.items():
            if char_name not in text:
                continue

            for fact, knowers in fact_knowers.items():
                if char_name in knowers:
                    continue  # Character knows this fact
                if len(knowers) == 0:
                    continue  # Nobody knows this fact

                # Check if the fact appears near the character in text
                if fact not in text:
                    continue

                # Proximity check: fact within 200 chars of character name
                char_positions = [m.start() for m in re.finditer(re.escape(char_name), text)]
                fact_positions = [m.start() for m in re.finditer(re.escape(fact), text)]

                for cp in char_positions:
                    for fp in fact_positions:
                        if abs(cp - fp) < 200:
                            # Get context
                            ctx_start = min(cp, fp) - 50
                            ctx_end = max(cp + len(char_name), fp + len(fact)) + 50
                            context = text[max(0, ctx_start):min(len(text), ctx_end)]

                            issues.append(CheckIssue(
                                category="information_boundary",
                                severity="warning",
                                dimension="信息边界",
                                description=f"角色「{char_name}」附近出现了其不应知道的信息「{fact[:30]}...」",
                                suggestion=f"确认「{char_name}」是否已通过合理途径获知此信息",
                                evidence=context,
                            ))
                            break
                    else:
                        continue
                    break

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    def _check_timeline_consistency(self, text: str, ws: WorldState, result: CodeCheckResult):
        """Basic timeline consistency: no obvious temporal contradictions."""
        result.checks_total += 1
        issues = []

        # Check for temporal regression markers
        regression_patterns = [
            (r'昨天.*前天', "时间顺序可能倒退"),
            (r'上个月.*这个月.*上周', "时间线交叉"),
        ]
        for pattern, desc in regression_patterns:
            if re.search(pattern, text):
                issues.append(CheckIssue(
                    category="timeline",
                    severity="warning",
                    dimension="时间线一致性",
                    description=f"检测到可能的时间线问题: {desc}",
                    suggestion="检查时间顺序是否合理",
                ))

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    def _check_subplot_stagnation(self, ws: WorldState, chapter_number: int,
                                   result: CodeCheckResult):
        """Active subplots should progress within N chapters."""
        result.checks_total += 1
        issues = []

        stalled = ws.subplot_board.get_stalled(stall_threshold=5, current_chapter=chapter_number)
        for sp in stalled:
            stall_chapters = chapter_number - sp.last_advanced
            issues.append(CheckIssue(
                category="subplot",
                severity="warning",
                dimension="子情节推进度",
                description=f"子情节「{sp.name}」已停滞 {stall_chapters} 章未推进",
                suggestion=f"在近期章节中推进「{sp.name}」，或标记为暂时搁置",
            ))

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    def _check_dialogue_ratio(self, text: str, result: CodeCheckResult):
        """Dialogue-to-narration ratio should be balanced."""
        result.checks_total += 1
        issues = []

        ratio = check_dialogue_ratio(text)
        if ratio < 0.1:
            issues.append(CheckIssue(
                category="style",
                severity="warning",
                dimension="对话/叙述比",
                description=f"对话占比过低 ({ratio:.0%})，可能导致阅读枯燥",
                suggestion="增加角色对话，减少大段叙述",
            ))
        elif ratio > 0.6:
            issues.append(CheckIssue(
                category="style",
                severity="warning",
                dimension="对话/叙述比",
                description=f"对话占比过高 ({ratio:.0%})，可能导致描写不足",
                suggestion="增加场景描写、心理描写和动作描写",
            ))

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    def _check_word_count(self, text: str, result: CodeCheckResult):
        """Chapter word count should be within target range."""
        result.checks_total += 1
        issues = []

        word_count = len(text)
        if word_count < 1200:
            issues.append(CheckIssue(
                category="word_count",
                severity="warning",
                dimension="字数合规",
                description=f"章节字数过少 ({word_count} 字)，目标 1500-3000",
                suggestion="补充场景描写或对话以达到最低字数",
                auto_fixable=True,
            ))
        elif word_count > 3600:
            issues.append(CheckIssue(
                category="word_count",
                severity="warning",
                dimension="字数合规",
                description=f"章节字数过多 ({word_count} 字)，目标 1500-3000",
                suggestion="精简冗余描写，压缩不必要的对话",
                auto_fixable=True,
            ))

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    def _check_anti_ai(self, text: str, result: CodeCheckResult):
        """Fatigue words and banned patterns check."""
        result.checks_total += 1
        issues = []

        fatigue = check_fatigue_words(text)
        for word, count in fatigue:
            issues.append(CheckIssue(
                category="anti_ai",
                severity="warning",
                dimension="疲劳词检测",
                description=f"「{word}」出现 {count} 次，属于高频 AI 用词",
                suggestion=f"替换「{word}」为更具体的描写",
                auto_fixable=True,
            ))

        patterns = check_banned_patterns(text)
        for p in patterns:
            issues.append(CheckIssue(
                category="anti_ai",
                severity="warning",
                dimension="禁用句式检测",
                description=p,
                suggestion="替换为非模板化的表达方式",
                auto_fixable=True,
            ))

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1
