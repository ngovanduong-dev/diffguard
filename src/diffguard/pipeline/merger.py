from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from diffguard.domain import (
    EvidenceStatus,
    FilterStatus,
    FindingCandidate,
    FixVerificationStatus,
    ReviewFinding,
    Severity,
    SourceType,
)
from diffguard.pipeline.grounding import CandidateEnvelope

_SEVERITY_RANK = {Severity.THAP: 1, Severity.TRUNG_BINH: 2, Severity.CAO: 3}
_WORD_RE = re.compile(r"[a-z0-9_]+")
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "line",
        "code",
        "function",
        "possible",
        "potential",
        "issue",
        "warning",
        "error",
        "check",
        "into",
        "when",
        "use",
    }
)

_RULE_FAMILIES = {
    "AST01": "mutable_default",
    "AST02": "broad_except",
    "AST03": "resource_leak",
    "AST04": "sql_injection",
    "AST05": "assert_non_test",
    "AST06": "regex_in_loop",
    "B608": "sql_injection",
    "S608": "sql_injection",
    "B602": "command_injection",
    "B603": "command_injection",
    "B604": "command_injection",
    "B605": "command_injection",
    "B606": "command_injection",
    "B607": "command_injection",
    "S602": "command_injection",
    "S603": "command_injection",
    "S604": "command_injection",
    "S605": "command_injection",
    "S606": "command_injection",
    "S607": "command_injection",
    "B102": "code_eval",
    "B307": "code_eval",
    "S102": "code_eval",
    "S307": "code_eval",
    "B105": "hardcoded_secret",
    "B106": "hardcoded_secret",
    "B107": "hardcoded_secret",
    "S105": "hardcoded_secret",
    "S106": "hardcoded_secret",
    "S107": "hardcoded_secret",
    "B303": "weak_crypto",
    "B304": "weak_crypto",
    "B324": "weak_crypto",
    "S303": "weak_crypto",
    "S304": "weak_crypto",
    "S324": "weak_crypto",
    "B301": "deserialization",
    "B403": "deserialization",
    "B506": "deserialization",
    "S301": "deserialization",
    "S506": "deserialization",
    "B501": "tls_verify",
    "S501": "tls_verify",
    "B110": "broad_except",
    "B112": "broad_except",
    "E722": "broad_except",
    "BLE001": "broad_except",
    "S110": "broad_except",
    "S112": "broad_except",
    "TRY_PASS": "broad_except",
    "B006": "mutable_default",
    "MUTABLE_DEFAULT": "mutable_default",
    "SIM115": "resource_leak",
    "UNCLOSED_RESOURCE": "resource_leak",
    "PATH_TRAVERSAL": "path_traversal",
    "F841": "unused_var",
    "F401": "unused_import",
    "F821": "undefined_name",
    "B310": "ssrf",
    "S310": "ssrf",
}

_TEXT_FAMILY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sql_injection", ("sql injection", "sqli", "formatted sql", "string-based query")),
    ("command_injection", ("command injection", "shell=true", "os.system")),
    ("code_eval", ("eval(", "exec(", "code injection", "arbitrary code")),
    ("hardcoded_secret", ("hardcoded", "secret key", "api key", "password literal")),
    ("weak_crypto", ("md5", "sha1", "weak hash", "insecure hash")),
    ("deserialization", ("pickle", "yaml.load", "unsafe deserializ")),
    ("tls_verify", ("verify=false", "certificate verification")),
    ("broad_except", ("broad except", "bare except", "swallow", "try/except/pass")),
    ("mutable_default", ("mutable default",)),
    ("resource_leak", ("resource leak", "unclosed", "never closed")),
    ("path_traversal", ("path traversal", "directory traversal")),
    ("none_deref", ("none dereference", "might be none", "is none", "attributeerror")),
    ("division_by_zero", ("division by zero", "divide by zero", "zerodivision")),
    ("n_plus_one", ("n+1", "query inside loop", "repeated query")),
    ("xss", ("cross-site scripting", "xss", "unescaped html")),
    ("ssrf", ("ssrf", "server-side request forgery")),
    ("unused_var", ("unused variable", "assigned to but never used")),
    ("undefined_name", ("undefined name",)),
)


@dataclass
class MergeResult:
    findings: list[ReviewFinding] = field(default_factory=list)
    updated_candidates: list[FindingCandidate] = field(default_factory=list)


def _detect_family(rule_code: str | None, text: str) -> str | None:
    if rule_code and rule_code in _RULE_FAMILIES:
        return _RULE_FAMILIES[rule_code]
    low = text.lower()
    for family, markers in _TEXT_FAMILY_PATTERNS:
        if any(m in low for m in markers):
            return family
    return None


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) >= 3 and w not in _STOPWORDS}


def _same_issue(a: CandidateEnvelope, b: CandidateEnvelope, line_tolerance: int) -> bool:
    ca, cb = a.candidate, b.candidate
    if ca.file_path != cb.file_path or ca.diff_side != cb.diff_side:
        return False
    if ca.category != cb.category or ca.finding_kind != cb.finding_kind:
        return False
    if max(ca.start_line, cb.start_line) > min(ca.end_line, cb.end_line) + line_tolerance:
        return False

    text_a = f"{ca.title} {ca.raw_message}"
    text_b = f"{cb.title} {cb.raw_message}"
    fam_a = _detect_family(ca.rule_code, text_a)
    fam_b = _detect_family(cb.rule_code, text_b)

    if ca.rule_code and cb.rule_code:
        if ca.rule_code == cb.rule_code:
            return True
        if fam_a is not None and fam_a == fam_b:
            return True
        return False

    if fam_a is not None and fam_b is not None:
        return fam_a == fam_b
    if fam_a is not None or fam_b is not None:
        kw_a, kw_b = _keywords(text_a), _keywords(text_b)
        if not kw_a or not kw_b:
            return False
        shared = len(kw_a & kw_b)
        return shared >= 2 and (shared / min(len(kw_a), len(kw_b))) >= 0.45

    norm_a = " ".join(text_a.lower().split())
    norm_b = " ".join(text_b.lower().split())
    if norm_a == norm_b:
        return True
    kw_a, kw_b = _keywords(text_a), _keywords(text_b)
    if not kw_a or not kw_b:
        return False
    shared = len(kw_a & kw_b)
    return shared >= 2 and (shared / min(len(kw_a), len(kw_b))) >= 0.45


def _pick_primary(cluster: list[CandidateEnvelope]) -> CandidateEnvelope:
    return max(
        cluster,
        key=lambda env: (
            _SEVERITY_RANK[env.candidate.severity],
            1 if env.candidate.source_type == SourceType.LLM else 0,
            1 if env.candidate.suggested_fix else 0,
            len(env.candidate.raw_message),
        ),
    )


class SemanticMerger:
    def __init__(self, line_tolerance: int = 2) -> None:
        self.line_tolerance = max(0, line_tolerance)

    def merge(self, envelopes: list[CandidateEnvelope]) -> MergeResult:
        clusters: list[list[CandidateEnvelope]] = []
        for env in envelopes:
            placed = False
            for cluster in clusters:
                if any(_same_issue(env, member, self.line_tolerance) for member in cluster):
                    cluster.append(env)
                    placed = True
                    break
            if not placed:
                clusters.append([env])

        findings: list[ReviewFinding] = []
        updated: list[FindingCandidate] = []
        used_fps: set[str] = set()

        for idx, cluster in enumerate(clusters):
            primary = _pick_primary(cluster)
            pc = primary.candidate
            start_line = min(e.candidate.start_line for e in cluster)
            end_line = max(e.candidate.end_line for e in cluster)
            hunk_index = next((e.hunk_index for e in cluster if e.hunk_index is not None), None)
            severity = max(cluster, key=lambda e: _SEVERITY_RANK[e.candidate.severity]).candidate.severity
            evidence_status = (
                EvidenceStatus.CO_CAN_CU
                if any(e.evidence_status == EvidenceStatus.CO_CAN_CU for e in cluster)
                else EvidenceStatus.CAN_XAC_MINH
            )
            sources = list(dict.fromkeys(e.candidate.source_type for e in cluster))
            rule_tags = [
                f"{e.candidate.source_type.value}:{e.candidate.rule_code}"
                for e in cluster
                if e.candidate.rule_code
            ]
            explanation = pc.raw_message
            if rule_tags and pc.source_type == SourceType.LLM:
                explanation = f"{pc.raw_message} (corroborated by {', '.join(rule_tags)})"
            code_evidence = max((e.candidate.code_evidence for e in cluster), key=len)
            suggested_fix = next(
                (e.candidate.suggested_fix for e in cluster if e.candidate.suggested_fix), None
            )

            fam = _detect_family(pc.rule_code, f"{pc.title} {pc.raw_message}")
            fp_seed = (
                f"{pc.file_path}|{pc.diff_side.value}|{start_line}|{end_line}|"
                f"{pc.category.value}|{pc.finding_kind.value}|{fam or pc.rule_code or pc.title}"
            )
            fp = hashlib.sha256(fp_seed.encode("utf-8")).hexdigest()[:40]
            if fp in used_fps:
                fp = hashlib.sha256(f"{fp_seed}|{idx}".encode()).hexdigest()[:40]
            used_fps.add(fp)

            findings.append(
                ReviewFinding(
                    issue_fingerprint=fp,
                    file_path=pc.file_path,
                    diff_side=pc.diff_side,
                    start_line=start_line,
                    end_line=end_line,
                    hunk_index=hunk_index,
                    category=pc.category,
                    finding_kind=pc.finding_kind,
                    severity=severity,
                    evidence_status=evidence_status,
                    title=pc.title[:300],
                    explanation=explanation,
                    code_evidence=code_evidence or pc.raw_message[:200],
                    suggested_fix=suggested_fix,
                    fix_verification_status=FixVerificationStatus.CHUA_KIEM_CHUNG,
                    sources=sources,
                )
            )

            primary_seen = False
            for env in cluster:
                if not primary_seen and env is primary:
                    primary_seen = True
                    updated.append(
                        env.candidate.model_copy(
                            update={"filter_status": FilterStatus.GIU_LAI, "merged_fingerprint": fp}
                        )
                    )
                else:
                    updated.append(
                        env.candidate.model_copy(
                            update={
                                "filter_status": FilterStatus.LOAI_TRUNG,
                                "filter_reason": f"merged_into:{fp[:16]}",
                                "merged_fingerprint": fp,
                            }
                        )
                    )

        return MergeResult(findings=findings, updated_candidates=updated)
