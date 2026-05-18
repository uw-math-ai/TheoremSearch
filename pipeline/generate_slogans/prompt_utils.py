import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import jinja2
from psycopg2.extensions import connection

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Fields that live in arxiv_paper_metadata but are exposed under the "paper" namespace.
_ARXIV_META_FIELDS = frozenset({
    "abstract", "preamble", "bibliography", "bibtex",
    "citation_count", "reference_ids", "journal_ref", "doi", "license",
})

# How much each extraction method contributes to a dependency's trust score.
# A dependency's trust is the sum across the methods that produced it. A dep
# whose only method is "judge" therefore scores 0 and is dropped before
# templates ever see it — judge alone is signal-free here.
_DEP_TRUST_POINTS = {
    "deterministic": 1.0,
    "heuristic":     0.7,
    "llm":           0.5,
    "judge":         0.0,
}


def _dep_trust(methods) -> float:
    if not methods:
        return 0.0
    return sum(_DEP_TRUST_POINTS.get(m, 0.0) for m in methods)

# Fields that live in informal_metadata but are exposed under the "statement" namespace.
_INFORMAL_META_FIELDS = frozenset({
    "ordinal", "ref", "label", "note", "pre_context", "post_context",
})


MODELS_FILE = Path(__file__).parent / "models.json"


@dataclass
class PromptSpec:
    name: str
    template: jinja2.Template
    source: str    # raw template string, used for namespace detection


def load_prompt(name: str) -> PromptSpec:
    """Load a prompt template from prompts/<name>.j2."""
    template_path = PROMPTS_DIR / f"{name}.j2"
    if not template_path.exists():
        raise FileNotFoundError(f"Prompt not found: {template_path}")

    source = template_path.read_text()
    env = jinja2.Environment(
        undefined=jinja2.Undefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.from_string(source)  # raises TemplateSyntaxError if malformed

    return PromptSpec(name=name, template=template, source=source)


def load_model_config(name: str) -> Dict[str, Any]:
    """Load a model config by short name from models.json."""
    if not MODELS_FILE.exists():
        raise FileNotFoundError(f"models.json not found at {MODELS_FILE}")
    models = json.loads(MODELS_FILE.read_text())
    if name not in models:
        available = ", ".join(f'"{k}"' for k in models)
        raise ValueError(f"Model '{name}' not found in models.json. Available: {available}")
    return models[name]


_INSUFFICIENT_PREFIX = "INSUFFICIENT CONTEXT"


def parse_slogan_text(text: str) -> tuple[str, bool]:
    """
    Strip the "INSUFFICIENT CONTEXT:" marker if present.
    Returns (cleaned_slogan, insufficient_context).
    """
    s = text.strip()
    if s.upper().startswith(_INSUFFICIENT_PREFIX):
        return s[len(_INSUFFICIENT_PREFIX):].lstrip(": \t"), True
    return s, False


def condition_joins(condition: str | None) -> str:
    """
    Build the JOIN suffix needed for a SELECT on `statement` when the user-supplied
    `-c` condition references `paper.` or `apm.` (arxiv_paper_metadata AS apm).
    Joining apm requires paper since apm is keyed off paper.external_id.
    """
    if not condition:
        return ""
    needs_apm   = bool(re.search(r"\bapm\s*\.", condition))
    needs_paper = needs_apm or bool(re.search(r"\bpaper\s*\.", condition))
    parts = []
    if needs_paper:
        parts.append(" JOIN paper ON paper.paper_id = statement.paper_id")
    if needs_apm:
        parts.append(" JOIN arxiv_paper_metadata AS apm ON apm.arxiv_id = paper.external_id")
    return "".join(parts)


def detect_needed_joins(template_source: str) -> Dict[str, bool]:
    """
    Scan a jinja2 template source for namespace references to determine the
    minimal set of SQL JOINs needed to populate the template context.

    Namespaces and their backing tables:
      statement.*         → statement (always) + informal_metadata (for meta fields)
      paper.*             → paper + arxiv_paper_metadata (for abstract/preamble/etc.)
      informal_dependency → informal_dependency, enriched with dep kind/body/proof
                            and cited paper title/authors/abstract via LEFT JOINs
      prev_statement      → adjacent statement (ordinal - 1, same paper); requires informal_meta
      next_statement      → adjacent statement (ordinal + 1, same paper); requires informal_meta
    """
    needs_paper = bool(re.search(r"\bpaper\s*\.", template_source))
    needs_arxiv_meta = needs_paper and any(
        re.search(rf"\bpaper\.{field}\b", template_source)
        for field in _ARXIV_META_FIELDS
    )
    needs_prev = bool(re.search(r"\bprev_statement\b", template_source))
    needs_next = bool(re.search(r"\bnext_statement\b", template_source))
    needs_informal_meta = (
        any(re.search(rf"\bstatement\.{field}\b", template_source) for field in _INFORMAL_META_FIELDS)
        or needs_prev
        or needs_next
    )
    needs_informal_dep = bool(re.search(r"\binformal_dependency\b", template_source))

    return {
        "paper":          needs_paper,
        "arxiv_meta":     needs_arxiv_meta,
        "informal_meta":  needs_informal_meta,
        "informal_dep":   needs_informal_dep,
        "prev_statement": needs_prev,
        "next_statement": needs_next,
    }


def fetch_contexts(
    conn: connection,
    statement_ids: List[str],
    joins: Dict[str, bool],
) -> Dict[str, Dict[str, Any]]:
    """
    Fetch context data for a batch of statement_ids using the minimal JOINs
    indicated by `joins` (from detect_needed_joins).

    Returns a dict mapping statement_id (str) → context dict. Possible keys:
      "statement"           always present (+ informal_metadata fields if joins["informal_meta"])
      "paper"               present if joins["paper"]
      "informal_dependency" present if joins["informal_dep"] (list, may be empty)
                            each row enriched with dep kind/body/proof and cite title/authors/abstract
      "prev_statement"      present if joins["prev_statement"] (dict or None)
      "next_statement"      present if joins["next_statement"] (dict or None)
    """
    select_parts = [
        "statement.statement_id",
        "statement.paper_id",
        "statement.formality",
        "statement.kind        AS stmt_kind",
        "statement.body",
        "statement.proof",
    ]
    join_clauses = []

    if joins["informal_meta"]:
        join_clauses.append(
            "LEFT JOIN informal_metadata ON informal_metadata.statement_id = statement.statement_id"
        )
        select_parts += [
            "informal_metadata.ordinal",
            "informal_metadata.ref        AS stmt_ref",
            "informal_metadata.label",
            "informal_metadata.note",
            "informal_metadata.pre_context",
            "informal_metadata.post_context",
        ]

    if joins["paper"]:
        join_clauses.append("JOIN paper ON paper.paper_id = statement.paper_id")
        select_parts += [
            "paper.kind        AS paper_kind",
            "paper.source",
            "paper.title",
            "paper.authors",
            "paper.url",
            "paper.external_id",
            "paper.categories",
            "paper.updated_at",
        ]

    if joins["arxiv_meta"]:
        join_clauses.append(
            "LEFT JOIN arxiv_paper_metadata ON arxiv_paper_metadata.arxiv_id = paper.external_id"
        )
        select_parts += [
            "arxiv_paper_metadata.abstract",
            "arxiv_paper_metadata.preamble",
            "arxiv_paper_metadata.bibliography",
            "arxiv_paper_metadata.bibtex",
            "arxiv_paper_metadata.citation_count",
            "arxiv_paper_metadata.reference_ids",
            "arxiv_paper_metadata.journal_ref",
            "arxiv_paper_metadata.doi",
            "arxiv_paper_metadata.license",
        ]

    query = (
        f"SELECT {', '.join(select_parts)}\n"
        f"FROM statement\n"
        + ("\n".join(join_clauses) + "\n" if join_clauses else "")
        + "WHERE statement.statement_id = ANY(%s::uuid[])"
    )

    contexts: Dict[str, Dict[str, Any]] = {}

    with conn.cursor() as cur:
        cur.execute(query, (statement_ids,))
        cols = [desc[0] for desc in cur.description]
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            sid = str(r["statement_id"])

            stmt: Dict[str, Any] = {
                "statement_id": r["statement_id"],
                "paper_id":     r["paper_id"],
                "formality":    r["formality"],
                "kind":         r["stmt_kind"],
                "body":         r["body"],
                "proof":        r["proof"],
            }
            if joins["informal_meta"]:
                stmt.update({
                    "ordinal":      r.get("ordinal"),
                    "ref":          r.get("stmt_ref"),
                    "label":        r.get("label"),
                    "note":         r.get("note"),
                    "pre_context":  r.get("pre_context"),
                    "post_context": r.get("post_context"),
                })

            ctx: Dict[str, Any] = {"statement": stmt}

            if joins["paper"]:
                paper: Dict[str, Any] = {
                    "kind":        r.get("paper_kind"),
                    "source":      r.get("source"),
                    "title":       r.get("title"),
                    "authors":     r.get("authors"),
                    "url":         r.get("url"),
                    "external_id": r.get("external_id"),
                    "categories":  r.get("categories"),
                    "updated_at":  r.get("updated_at"),
                }
                if joins["arxiv_meta"]:
                    paper.update({
                        "abstract":       r.get("abstract"),
                        "preamble":       r.get("preamble"),
                        "bibliography":   r.get("bibliography"),
                        "bibtex":         r.get("bibtex"),
                        "citation_count": r.get("citation_count"),
                        "reference_ids":  r.get("reference_ids"),
                        "journal_ref":    r.get("journal_ref"),
                        "doi":            r.get("doi"),
                        "license":        r.get("license"),
                    })
                ctx["paper"] = paper

            contexts[sid] = ctx

    # Enriched dependency fetch: dep kind/body/proof + cited paper title/authors/abstract.
    if joins["informal_dep"]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id.src_id, id.location, id.cite_id, id.cite_key,
                    id.dep_id, id.dep_key, id.dep_name, id.methods,
                    ds.kind        AS dep_kind,
                    ds.body        AS dep_body,
                    ds.proof       AS dep_proof,
                    cp.title       AS cite_title,
                    cp.authors     AS cite_authors,
                    apm.abstract   AS cite_abstract
                FROM informal_dependency id
                LEFT JOIN statement ds  ON ds.statement_id = id.dep_id
                LEFT JOIN paper cp      ON cp.paper_id = id.cite_id
                LEFT JOIN arxiv_paper_metadata apm ON apm.arxiv_id = cp.external_id
                WHERE id.src_id = ANY(%s::uuid[])
                """,
                (statement_ids,),
            )
            dep_cols = [desc[0] for desc in cur.description]
            for row in cur.fetchall():
                r = dict(zip(dep_cols, row))
                sid = str(r["src_id"])
                if sid in contexts:
                    contexts[sid].setdefault("informal_dependency", []).append(r)

        for ctx in contexts.values():
            ctx.setdefault("informal_dependency", [])

        # Score each dep by the sum of its method trust points, drop deps that
        # score 0 (no methods, or methods=={"judge"}), and order most→least
        # trustworthy so templates can present them that way.
        for ctx in contexts.values():
            scored = []
            for d in ctx["informal_dependency"]:
                trust = _dep_trust(d.get("methods"))
                if trust <= 0:
                    continue
                scored.append({**d, "trust": trust})
            scored.sort(key=lambda d: d["trust"], reverse=True)
            ctx["informal_dependency"] = scored

    # Adjacent statement fetch: prev (ordinal - 1) and/or next (ordinal + 1), same paper.
    if joins["prev_statement"] or joins["next_statement"]:
        sub_queries = []
        if joins["prev_statement"]:
            sub_queries.append((
                "prev",
                """
                SELECT im_src.statement_id AS src_id, 'prev' AS direction,
                       s_adj.kind, s_adj.body, s_adj.proof
                FROM informal_metadata im_src
                JOIN statement src ON src.statement_id = im_src.statement_id
                JOIN informal_metadata im_adj ON im_adj.ordinal = im_src.ordinal - 1
                JOIN statement s_adj ON s_adj.statement_id = im_adj.statement_id
                    AND s_adj.paper_id = src.paper_id
                WHERE im_src.statement_id = ANY(%s::uuid[])
                """,
            ))
        if joins["next_statement"]:
            sub_queries.append((
                "next",
                """
                SELECT im_src.statement_id AS src_id, 'next' AS direction,
                       s_adj.kind, s_adj.body, s_adj.proof
                FROM informal_metadata im_src
                JOIN statement src ON src.statement_id = im_src.statement_id
                JOIN informal_metadata im_adj ON im_adj.ordinal = im_src.ordinal + 1
                JOIN statement s_adj ON s_adj.statement_id = im_adj.statement_id
                    AND s_adj.paper_id = src.paper_id
                WHERE im_src.statement_id = ANY(%s::uuid[])
                """,
            ))

        adj_query = "\nUNION ALL\n".join(sql for _, sql in sub_queries)
        with conn.cursor() as cur:
            cur.execute(adj_query, [statement_ids] * len(sub_queries))
            adj_cols = [desc[0] for desc in cur.description]
            for row in cur.fetchall():
                r = dict(zip(adj_cols, row))
                sid = str(r["src_id"])
                if sid in contexts:
                    contexts[sid][r["direction"] + "_statement"] = {
                        "kind":  r["kind"],
                        "body":  r["body"],
                        "proof": r["proof"],
                    }

        for ctx in contexts.values():
            if joins["prev_statement"]:
                ctx.setdefault("prev_statement", None)
            if joins["next_statement"]:
                ctx.setdefault("next_statement", None)

    return contexts


def register_prompt(conn: connection, spec: PromptSpec) -> None:
    """
    Ensure this prompt is registered in slogan_prompt.

    - New name → insert and commit.
    - Existing name, same template → no-op.
    - Existing name, different template → raise ValueError with rename guidance.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT template FROM slogan_prompt WHERE name = %s", (spec.name,))
        row = cur.fetchone()

    if row is None:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO slogan_prompt (name, template) VALUES (%s, %s)",
                (spec.name, spec.source),
            )
        conn.commit()
        return

    (db_template,) = row
    if db_template != spec.source:
        raise ValueError(
            f"Prompt '{spec.name}' exists in the database but prompt.j2 has changed.\n"
            f"Rename the prompt file (e.g. '{spec.name}-v2.j2') to register it as a new version."
        )


def register_model(conn: connection, name: str, config: Dict[str, Any]) -> None:
    """
    Ensure this model is registered in slogan_model.

    - New name → insert and commit.
    - Existing name, same config → no-op.
    - Existing name, different config → raise ValueError with rename guidance.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT model, temperature, max_tokens FROM slogan_model WHERE name = %s",
            (name,),
        )
        row = cur.fetchone()

    if row is None:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO slogan_model (name, model, temperature, max_tokens) VALUES (%s, %s, %s, %s)",
                (name, config["model"], config.get("temperature"), config.get("max_tokens")),
            )
        conn.commit()
        return

    db_model, db_temperature, db_max_tokens = row

    mismatches = []
    if db_model != config["model"]:
        mismatches.append(f"model ({db_model!r} → {config['model']!r})")
    if db_temperature != config.get("temperature"):
        mismatches.append(f"temperature ({db_temperature} → {config.get('temperature')})")
    if db_max_tokens != config.get("max_tokens"):
        mismatches.append(f"max_tokens ({db_max_tokens} → {config.get('max_tokens')})")

    if mismatches:
        raise ValueError(
            f"Model '{name}' exists in the database but models.json has changed: "
            + ", ".join(mismatches) + ".\n"
            f"Rename the entry (e.g. '{name}-v2') to register it as a new version."
        )


def render_prompt(template: jinja2.Template, context: Dict[str, Any]) -> str:
    """Render a jinja2 template with the given statement context."""
    return template.render(**context).strip()
