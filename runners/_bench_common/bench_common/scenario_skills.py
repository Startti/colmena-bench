"""Demo #9 — Colmena Seguros knowledge-pack corpus generator.

PIVOT: from "finance rules computed over a CSV" to EXTRACTIVE POLICY QA over a
fictional insurer, Colmena Seguros. Each pack is an insurance policy with
perils -> sub-conditions -> a leaf holding company-specific NON-GUESSABLE values.

SINGLE SOURCE OF TRUTH: `policy_value(pack, peril, sub, field)` deterministically
derives every company-specific number from the pack/peril/sub/field names. BOTH
the rendered leaf tables AND the (later) expected answers read from it, so the
markdown and the answer key can never drift. Distractor packs are GENERATED
insurance policies (same structure, different names/values) — a realistic book of
N policies among which RAG must find the right one.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Leaf:
    """A reference file in a pack's tree. May declare nested children."""
    name: str
    description: str                      # frontmatter description (catalog-visible)
    body: str                            # markdown body
    children: dict[str, "Leaf"] = field(default_factory=dict)


@dataclass
class CorePack:
    name: str                            # == directory name == frontmatter name
    description: str                     # SKILL.md catalog description (when to / not to use)
    overview: str                        # SKILL.md body
    references: dict[str, Leaf]          # top-level reference files


# ---------------------------------------------------------------------------
# The policy model (single source of truth)
# ---------------------------------------------------------------------------

# 6 core policies questions will target. Two homeowners variants on purpose
# (same perils, DIFFERENT values) to force precise navigation.
CORE_POLICY_NAMES = [
    "colmena-hogar-premium", "colmena-hogar-basico", "colmena-auto-full",
    "colmena-viaje-internacional", "colmena-salud-familiar", "colmena-mascotas",
]

# Domain-appropriate perils per policy; each peril has 2 UNIQUE-NAMED sub-conditions
# (unique within the pack so the FLAT references/<sub>.md layout never collides).
POLICY_PERILS: dict[str, dict[str, list[str]]] = {
    "colmena-hogar-premium": {
        "danio-agua": ["agua-subita", "agua-gradual"],
        "incendio": ["incendio-estructura", "incendio-contenido"],
        "robo": ["robo-domicilio", "robo-fuera"],
        "responsabilidad-civil": ["rc-personal", "rc-huesped"],
    },
    "colmena-hogar-basico": {
        "danio-agua": ["agua-basica-subita", "agua-basica-gradual"],
        "incendio": ["incendio-basico-estructura", "incendio-basico-contenido"],
        "robo": ["robo-basico-domicilio", "robo-basico-fuera"],
    },
    "colmena-auto-full": {
        "colision": ["colision-propio", "colision-tercero"],
        "robo-vehiculo": ["robo-total", "robo-parcial"],
        "cristales": ["cristal-parabrisas", "cristal-lateral"],
        "asistencia": ["grua", "auto-sustituto"],
    },
    "colmena-viaje-internacional": {
        "gastos-medicos": ["medico-ambulatorio", "medico-hospital"],
        "cancelacion": ["cancela-anticipada", "cancela-interrupcion"],
        "equipaje": ["equipaje-demora", "equipaje-perdida"],
    },
    "colmena-salud-familiar": {
        "hospitalizacion": ["hosp-habitacion", "hosp-cirugia"],
        "ambulatorio": ["amb-consulta", "amb-laboratorio"],
        "maternidad": ["mat-parto", "mat-prenatal"],
    },
    "colmena-mascotas": {
        "veterinario": ["vet-consulta", "vet-cirugia"],
        "accidente": ["acc-fractura", "acc-intoxicacion"],
    },
}

# The numeric fields every sub-condition leaf carries.
POLICY_FIELDS = ["deductible_usd", "coverage_limit_usd", "waiting_period_days", "copay_pct"]


def _det_int(seed: str, lo: int, hi: int) -> int:
    h = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    return lo + (h % (hi - lo + 1))


def policy_value(pack: str, peril: str, sub: str, field: str) -> int:
    """Deterministic, non-round, company-specific value. Distinct per
    (pack,peril,sub,field) so a wrong leaf yields a wrong answer."""
    seed = f"{pack}|{peril}|{sub}|{field}"
    if field == "deductible_usd":
        return _det_int(seed, 110, 990)          # e.g. 437 — non-round
    if field == "coverage_limit_usd":
        return _det_int(seed, 5000, 95000)
    if field == "waiting_period_days":
        return _det_int(seed, 3, 89)
    if field == "copay_pct":
        return _det_int(seed, 5, 39)
    raise ValueError(field)


def policy_facts(pack: str, perils: dict[str, list[str]]) -> dict[str, dict[str, dict[str, int]]]:
    """Single source of truth as a nested dict for a given pack/perils. BOTH the
    rendered tables and the (later) expected answers read from policy_value, so
    they cannot drift."""
    return {
        peril: {
            sub: {f: policy_value(pack, peril, sub, f) for f in POLICY_FIELDS}
            for sub in subs
        }
        for peril, subs in perils.items()
    }


# Human-readable Spanish labels for perils (for prose; falls back to the key).
_PERIL_LABELS = {
    "danio-agua": "daño por agua",
    "incendio": "incendio",
    "robo": "robo",
    "responsabilidad-civil": "responsabilidad civil",
    "colision": "colisión",
    "robo-vehiculo": "robo del vehículo",
    "cristales": "rotura de cristales",
    "asistencia": "asistencia en viaje",
    "gastos-medicos": "gastos médicos",
    "cancelacion": "cancelación de viaje",
    "equipaje": "equipaje",
    "hospitalizacion": "hospitalización",
    "ambulatorio": "atención ambulatoria",
    "maternidad": "maternidad",
    "veterinario": "atención veterinaria",
    "accidente": "accidente",
    # generic distractor perils
    "perdida": "pérdida",
    "fraude": "fraude",
    "interrupcion": "interrupción",
}


def _peril_label(peril: str) -> str:
    return _PERIL_LABELS.get(peril, peril.replace("-", " "))


def _product_label(name: str) -> str:
    """colmena-hogar-premium -> Colmena Hogar Premium."""
    return " ".join(w.capitalize() for w in name.split("-"))


# ---------------------------------------------------------------------------
# Build a policy pack into the existing CorePack/Leaf tree
# ---------------------------------------------------------------------------

def _render_values_table(pack: str, peril: str, sub: str) -> str:
    """Markdown table of the company-specific values for one sub-condition leaf.
    Reads from policy_value so it is the single source of truth."""
    rows = []
    for f in POLICY_FIELDS:
        v = policy_value(pack, peril, sub, f)
        rows.append(f"| {f} | {v} |")
    body = "\n".join(rows)
    return f"| campo | valor |\n|---|---|\n{body}\n"


def _sub_leaf_body(pack: str, peril: str, sub: str) -> str:
    """A values table plus realistic Spanish clause prose. The prose density keeps
    the corpus above the token floor; the table carries the answerable facts."""
    label = _peril_label(peril)
    ded = policy_value(pack, peril, sub, "deductible_usd")
    lim = policy_value(pack, peril, sub, "coverage_limit_usd")
    esp = policy_value(pack, peril, sub, "waiting_period_days")
    cop = policy_value(pack, peril, sub, "copay_pct")
    return (
        f"# Sub-condición: {sub}\n\n"
        f"Esta sub-condición aplica a la cobertura de {label} bajo la póliza "
        f"{_product_label(pack)}, sub-condición específica '{sub}'. Las "
        f"condiciones particulares que se detallan a continuación prevalecen "
        f"sobre las condiciones generales del producto.\n\n"
        f"## Valores aplicables\n\n"
        + _render_values_table(pack, peril, sub) +
        f"\nEl asegurado deberá asumir un **deducible de USD {ded}** por cada "
        f"siniestro amparado por esta sub-condición antes de que la compañía "
        f"reconozca indemnización alguna. El **límite de cobertura** por evento "
        f"asciende a **USD {lim}**, que constituye el monto máximo que Colmena "
        f"Seguros pagará por la suma de daños directos e indirectos derivados de "
        f"un mismo hecho generador.\n\n"
        f"Aplica un **período de espera (carencia) de {esp} días** contados desde "
        f"la fecha de inicio de vigencia; los siniestros ocurridos dentro de ese "
        f"plazo no generan derecho a indemnización. Sobre el monto indemnizable, "
        f"el asegurado participa con un **copago del {cop}%**, que se descuenta de "
        f"la liquidación final. Para hacer efectiva la cobertura, el asegurado "
        f"debe notificar el siniestro dentro de los plazos establecidos y aportar "
        f"la documentación de respaldo que la compañía requiera para la valoración "
        f"del reclamo.\n\n"
        f"## Exclusiones y condiciones particulares\n\n"
        f"Quedan excluidos de esta sub-condición los siniestros derivados de dolo "
        f"o culpa grave del asegurado, los hechos preexistentes a la contratación "
        f"de la póliza {_product_label(pack)} y aquellos que no hayan sido "
        f"notificados dentro del plazo contractual. La indemnización por "
        f"'{sub}' nunca podrá superar el límite de USD {lim} indicado en la tabla "
        f"de valores, ni aplicarse antes de cumplido el período de espera de "
        f"{esp} días. En caso de concurrencia con otra cobertura de la misma "
        f"póliza, se aplicará el deducible más alto entre los aplicables y un "
        f"único copago del {cop}% sobre el monto neto indemnizable. La compañía "
        f"podrá solicitar peritajes independientes antes de aprobar cualquier "
        f"pago bajo la sub-condición '{sub}'.\n"
    )


def _peril_leaf(pack: str, peril: str, subs: list[str]) -> Leaf:
    label = _peril_label(peril)
    sub_list = ", ".join(subs)
    body = (
        f"# Cobertura: {label}\n\n"
        f"La cobertura de {label} de la póliza {_product_label(pack)} se "
        f"desglosa en las siguientes sub-condiciones, cada una con sus propios "
        f"deducibles, límites, períodos de espera y copagos: {sub_list}. "
        f"Consultá la sub-condición que corresponda al caso concreto del "
        f"asegurado para obtener los valores aplicables; los importes pueden "
        f"variar de forma significativa entre una sub-condición y otra.\n"
    )
    children = {
        sub: Leaf(
            name=sub,
            description=(
                f"Valores (deducible, límite, espera, copago) de la "
                f"sub-condición '{sub}' de la cobertura de {label}."
            ),
            body=_sub_leaf_body(pack, peril, sub),
        )
        for sub in subs
    }
    return Leaf(
        name=peril,
        description=(
            f"Cobertura de {label}. Sub-condiciones: {sub_list}."
        ),
        body=body,
        children=children,
    )


def _build_policy_pack(name: str, perils: dict[str, list[str]]) -> CorePack:
    """Build a CorePack for an insurance policy from its peril->sub structure.
    Values come from policy_value (single source of truth)."""
    peril_labels = ", ".join(_peril_label(p) for p in perils)
    overview = (
        f"# Póliza {_product_label(name)}\n\n"
        f"Póliza {_product_label(name)}. Cubre: {peril_labels}. Para cada "
        f"cobertura, consultá la referencia correspondiente y su sub-condición "
        f"para obtener los valores particulares (deducible, límite de cobertura, "
        f"período de espera y copago).\n\n"
        f"Cada cobertura de esta póliza se subdivide en sub-condiciones con "
        f"importes propios; los valores no son comunes a todos los productos de "
        f"Colmena Seguros, de modo que es indispensable navegar hasta la "
        f"sub-condición exacta antes de informar cualquier cifra al cliente.\n"
    )
    references = {
        peril: _peril_leaf(name, peril, subs) for peril, subs in perils.items()
    }
    description = (
        f"Use when the customer asks about the {_product_label(name)} policy: "
        f"{peril_labels}. NOT for other Colmena Seguros products."
    )
    return CorePack(
        name=name,
        description=description,
        overview=overview,
        references=references,
    )


CORE_PACKS: dict[str, CorePack] = {
    name: _build_policy_pack(name, POLICY_PERILS[name]) for name in CORE_POLICY_NAMES
}


# ---------------------------------------------------------------------------
# Question bank — RW-B will restore the customer-facing question set + scorer.
# Kept as empty stubs so this module stays importable during the pivot.
# ---------------------------------------------------------------------------

@dataclass
class Question:
    id: str
    pack: str
    text: str                 # natural language; never names the pack mechanic explicitly
    leaf_path: str            # e.g. "danio-agua/agua-subita" — where the fact lives
    field: str = ""           # which POLICY_FIELDS value the question targets


QUESTION_BANK: list = []  # RW-B will restore


def leaf_path_exists(pack_name: str, leaf_path: str) -> bool:
    node = CORE_PACKS[pack_name].references
    parts = leaf_path.split("/")
    cur = node.get(parts[0])
    for p in parts[1:]:
        if cur is None:
            return False
        cur = cur.children.get(p)
    return cur is not None


# ---------------------------------------------------------------------------
# Rendering: pack object -> {relpath: markdown content} with frontmatter
# ---------------------------------------------------------------------------

def _yaml_dq(s: str) -> str:
    """Double-quoted YAML scalar (safe for colons, #, etc.)."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _frontmatter(name: str, description: str, child_refs: list[Leaf]) -> str:
    lines = ["---", f"name: {name}", f"description: {_yaml_dq(description)}"]
    if child_refs:
        lines.append("references:")
        for c in child_refs:
            lines.append(f"  - name: {c.name}")
            lines.append(f"    description: {_yaml_dq(c.description)}")
    lines.append("---\n")
    return "\n".join(lines)


def _render_leaf(key: str, leaf: Leaf, out: dict[str, str]) -> None:
    # Colmena stores ALL reference files FLAT in references/<name>.md; nesting is
    # declared logically in each file's frontmatter (children listed under
    # `references:`), NOT via subdirectories. So write flat and recurse.
    children = list(leaf.children.values())
    out[f"references/{key}.md"] = _frontmatter(leaf.name, leaf.description, children) + leaf.body
    for ck, cl in leaf.children.items():
        _render_leaf(ck, cl, out)


def render_pack(pack: CorePack) -> dict[str, str]:
    """Return {relpath: content} for the whole pack. SKILL.md + a FLAT references/
    dir (Colmena reads references/<name>.md flat; the tree is declared in
    frontmatter, navigated via load_skill(pack, 'parent/child'))."""
    out: dict[str, str] = {}
    top = list(pack.references.values())
    out["SKILL.md"] = _frontmatter(pack.name, pack.description, top) + pack.overview
    for key, leaf in pack.references.items():
        _render_leaf(key, leaf, out)
    return out


# ---------------------------------------------------------------------------
# Distractor packs + corpus materialization
# ---------------------------------------------------------------------------
# Distractor packs are ALSO generated insurance policies: same structure,
# different names/values. They form a realistic "book of N policies" among which
# RAG must find the right one. The whole point of the demo is that naive
# prompt-stuffing the corpus is expensive (>=150k tokens at M=50).

_DISTRACTOR_PRODUCTS = [
    "hogar", "auto", "viaje", "salud", "mascotas", "vida", "pyme", "moto",
    "bicicleta", "celular", "dental", "vision", "agro", "comercio",
]
_DISTRACTOR_REGIONS = [
    "norte", "sur", "centro", "este", "oeste", "metropolitana", "costa",
    "andina", "pacifico", "caribe", "litoral", "valle",
]

# A generic 3-peril x 2-sub template for distractor policies. Sub keys are made
# unique within each distractor pack by suffixing with the pack name (see
# _distractor_perils), so the FLAT references/<sub>.md layout never collides.
_DISTRACTOR_PERIL_TEMPLATE = {
    "danio-agua": ["agua-subita", "agua-gradual"],
    "robo": ["robo-domicilio", "robo-fuera"],
    "responsabilidad-civil": ["rc-personal", "rc-huesped"],
}


def _distractor_perils(name: str) -> dict[str, list[str]]:
    """Generic peril structure for a distractor policy, with sub keys made unique
    within this pack by suffixing the (already-unique) pack name."""
    tag = name.replace("colmena-", "")
    return {
        peril: [f"{sub}-{tag}" for sub in subs]
        for peril, subs in _DISTRACTOR_PERIL_TEMPLATE.items()
    }


def _distractor_names(n: int, seed: int) -> list[str]:
    """`n` deterministic, plausible Colmena Seguros product names, DISTINCT from
    the 6 core names and from each other. Seeded-shuffled product x region pool,
    suffixed if the pool exhausts."""
    import random
    rng = random.Random(f"distract-{n}-{seed}")
    pool = [
        f"colmena-{prod}-{region}"
        for prod in _DISTRACTOR_PRODUCTS
        for region in _DISTRACTOR_REGIONS
    ]
    pool = [p for p in pool if p not in CORE_PACKS]
    rng.shuffle(pool)
    chosen: list[str] = []
    seen: set[str] = set(CORE_PACKS)
    i = 0
    suffix = 0
    while len(chosen) < n:
        if i < len(pool):
            cand = pool[i]
            i += 1
        else:
            suffix += 1
            cand = pool[(suffix - 1) % len(pool)] + f"-{suffix}"
        if cand in seen:
            continue
        seen.add(cand)
        chosen.append(cand)
    return chosen


def _write_files(pack_dir: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        fp = pack_dir / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)


def materialize_corpus(out_dir: str, pack_count: int, seed: int) -> str:
    """Write `pack_count` policy packs to out_dir: core packs first (always
    present when pack_count >= number of core packs), the remainder filled with
    deterministic GENERATED insurance-policy distractors. Returns out_dir.
    Idempotent (clears out_dir first); refuses to clear a non-corpus dir."""
    root = Path(out_dir)
    sentinel = root / ".colmena_corpus"
    if root.exists():
        # Safety: only clear a dir that is empty or that we previously created
        # (marked with the sentinel). Refuse anything else so a bad path can't
        # silently delete user data.
        if any(root.iterdir()) and not sentinel.exists():
            raise ValueError(
                f"refusing to clear {root!s}: not empty and missing .colmena_corpus "
                f"sentinel (not a corpus dir created by materialize_corpus)"
            )
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / ".colmena_corpus").write_text("demo09 corpus\n")

    core_items = list(CORE_PACKS.items())
    if pack_count <= len(core_items):
        for name, pack in core_items[:pack_count]:
            _write_files(root / name, render_pack(pack))
        return out_dir

    for name, pack in core_items:
        _write_files(root / name, render_pack(pack))
    n_distract = pack_count - len(core_items)
    for name in _distractor_names(n_distract, seed):
        pack = _build_policy_pack(name, _distractor_perils(name))
        _write_files(root / name, render_pack(pack))
    return out_dir


def corpus_token_estimate(corpus_dir: str) -> int:
    """~4 chars/token estimate over every .md file in the corpus."""
    total = sum(len(p.read_text()) for p in Path(corpus_dir).rglob("*.md"))
    return total // 4


# ---------------------------------------------------------------------------
# Scorer — RW-C will restore exact-match grading against policy_value.
# Minimal stub kept so this module stays importable during the pivot.
# ---------------------------------------------------------------------------

def _parse_number(text):
    """First numeric value in a string, tolerant of commas, currency symbols,
    surrounding prose, signs, and scientific notation. Returns None if no number
    is present (the honesty rule: unparseable -> not measured, never 0.0)."""
    if text is None:
        return None
    cleaned = re.sub(r"[,$€£]", "", str(text))
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][+-]?\d+)?", cleaned)
    return float(m.group()) if m else None


def score_skill_answer(question, produced: str, df=None) -> dict:  # RW-C will restore
    """STUB — RW-C will restore exact-match grading against policy_value.
    For now returns 'not measured' so the module stays importable."""
    return {"correct": None, "want": None, "got": _parse_number(produced)}


# ---------------------------------------------------------------------------
# Naive prompt builder
# ---------------------------------------------------------------------------

def build_naive_system_prompt(corpus_dir: str) -> str:
    """Concatenate EVERY pack's full markdown tree — the naive arm's strategy.

    Produces a single system-prompt string containing all pack content. At
    M=50 this exceeds 150k tokens, making it the expensive baseline against
    which Colmena's progressive-load arm is compared.
    """
    parts = [
        "Sos un asesor de Colmena Seguros. A continuación está el manual "
        "completo de pólizas. Respondé usando la póliza y sub-condición "
        "correctas. Manual:\n"
    ]
    for md in sorted(Path(corpus_dir).rglob("*.md")):
        parts.append(f"\n\n===== {md.relative_to(corpus_dir)} =====\n{md.read_text()}")
    return "".join(parts)
