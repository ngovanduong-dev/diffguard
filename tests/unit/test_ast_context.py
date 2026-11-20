from diffguard.context import extract_ast_index, pack_context_budget
from diffguard.domain import ContextPolicy, ReviewPolicy
from diffguard.ingest import ingest_snapshot_pair


def test_ast_context_enclosing_and_cross_callee_and_circular_imports() -> None:
    base_a = "from b import helper\n\ndef compute(x):\n    return helper(x)\n"
    head_a = "from b import helper\n\ndef compute(x):\n    return helper(x + 1)\n"
    head_b = "from a import compute\n\ndef helper(val: int) -> int:\n    return val * 2\n"

    ing = ingest_snapshot_pair(
        "org/demo",
        base_files={"a.py": base_a, "b.py": head_b},
        head_files={"a.py": head_a, "b.py": head_b},
        pr_title="Fix offset",
        pr_description="Increment input before helper call",
    )
    bundle = pack_context_budget(
        ing.parsed_files,
        ing.base_contents,
        ing.head_contents,
        ContextPolicy.DIFF_AST_INTENT,
        ReviewPolicy(max_input_tokens=4000),
        pr_title=ing.snapshot.pr_title,
        pr_description=ing.snapshot.pr_description,
    )
    assert bundle.is_full_coverage is True
    assert bundle.pr_intent_text is not None and "Fix offset" in bundle.pr_intent_text
    assert len(bundle.chunks) == 1
    ch = bundle.chunks[0]
    assert ch.ast_symbol_name == "compute"
    assert ch.ast_context_text is not None
    assert "def helper(val: int) -> int:" in ch.ast_context_text


def test_context_policies_and_syntax_error_fallback() -> None:
    idx = extract_ast_index("def broken(:\n", "broken.py")
    assert idx.parse_error is not None

    ing = ingest_snapshot_pair(
        "org/demo",
        base_files={"a.py": "def f():\n    return 1\n"},
        head_files={"a.py": "def f():\n    return 2\n"},
    )
    diff_only = pack_context_budget(
        ing.parsed_files,
        ing.base_contents,
        ing.head_contents,
        ContextPolicy.DIFF_ONLY,
        ReviewPolicy(),
    )
    assert diff_only.chunks[0].ast_context_text is None
    assert diff_only.chunks[0].selection_reason == "diff-only"


def test_token_budget_overflow_flags_incomplete_coverage() -> None:
    big_fn = "def big():\n" + "\n".join(f"    x{i} = {i}" for i in range(120)) + "\n"
    ing = ingest_snapshot_pair(
        "org/demo",
        base_files={"a.py": "def big():\n    pass\n"},
        head_files={"a.py": big_fn},
    )
    bundle = pack_context_budget(
        ing.parsed_files,
        ing.base_contents,
        ing.head_contents,
        ContextPolicy.DIFF_AST,
        ReviewPolicy(max_input_tokens=560),
        prompt_overhead_tokens=500,
    )
    assert bundle.is_full_coverage is False
    assert "a.py" in bundle.omitted_files or any("Trimmed" in w or "Omitted" in w for w in bundle.warnings)
