"""The floor every new or changed OpenAPI operation stands on (ADR-076 §7).

The AI assistant will run a company's account through the operations the panel
calls (ADR-033), so an operation has to say what it is and how it fails: an
explicit name, a summary and a description, a required Idempotency-Key on a
mutation, and a 400 answered with Problem Details when it takes data. Most of
today's operations miss part of that. Their debt is written down once in
`packages/contracts/openapi/quality-baseline.json` and may only shrink: a new
operation meets every rule, and an operation whose parameters, request body or
success responses change loses what it was forgiven.

Pure functions over the committed `v1.yaml`, without Django, so this one file
is both the pytest gate and `pnpm api:quality`. `pnpm api:quality
--write-baseline` shrinks the baseline, or writes it when there is none.
"""

import argparse
import copy
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

REPOSITORY = Path(__file__).resolve().parents[3]
CONTRACT = Path("packages/contracts/openapi/v1.yaml")
CORE_BASELINE = CONTRACT.with_name("quality-baseline.json")
#: A product repository never edits a file it received from the core (ADR-049),
#: so the debt of its own operations lives in a file of its own.
PRODUCT_BASELINE = CONTRACT.with_name("quality-baseline.product.json")
UPSTREAM_MARKER = Path(".saas-core-upstream")
WRITE = "`pnpm api:quality --write-baseline`"

RULES = ("operation-id", "summary", "description", "idempotency-key", "error-400")
#: The only rules an operation may waive, and only with a reason: a naturally
#: idempotent mutation needs no key, an input that cannot be wrong needs no 400.
EXEMPTABLE = frozenset({"idempotency-key", "error-400"})
METHODS = ("get", "put", "post", "patch", "delete")
MUTATIONS = frozenset({"put", "post", "patch", "delete"})
#: The action drf-spectacular appends to an unnamed operation's path. A GET is
#: `list` or `retrieve` depending on the view, which the contract does not say.
AUTOMATIC_ACTIONS = {
    "get": ("list", "retrieve"),
    "put": ("update",),
    "post": ("create",),
    "patch": ("partial_update",),
    "delete": ("destroy",),
}
PROBLEM_DETAILS = "#/components/schemas/ProblemDetails"
SNAKE_CASE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")
#: drf-spectacular gives the second holder of an operationId a `_2` suffix and
#: only logs a warning, so a duplicated explicit id would reach the client.
DEDUPLICATED = re.compile(r"(.+)_(\d+)")

#: The keywords that decide which values a schema accepts. The rest — title,
#: description, example(s), default, readOnly, writeOnly, x-* — is
#: documentation as far as a fingerprint is concerned.
SHAPE_KEYWORDS = frozenset({
    "$ref",
    "type",
    "format",
    "enum",
    "const",
    "nullable",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
})
SUBSCHEMA_KEYWORDS = frozenset({"items", "additionalProperties", "not"})
SUBSCHEMA_LIST_KEYWORDS = frozenset({"allOf", "oneOf", "anyOf", "prefixItems"})

type Document = Mapping[str, Any]
type Baseline = dict[str, Any]
#: Each operation's fingerprint and broken rules by `METHOD path`: the shape
#: of a baseline's `operations`.
type Audit = dict[str, dict[str, Any]]


def operations(document: Document) -> Iterator[tuple[str, str, Mapping[str, Any]]]:
    for path, item in (document.get("paths") or {}).items():
        for method in METHODS:
            if method in item:
                yield method, path, item[method]


def operation_key(method: str, path: str) -> str:
    return f"{method.upper()} {path}"


def automatic_operation_ids(method: str, path: str) -> set[str]:
    """The ids drf-spectacular gives an operation nobody named (`get_operation_id`).

    The path loses its `{parameters}`, its segments are joined with `_` and a
    `-` becomes `_`, then the method's action follows. The generator strips
    only the prefix every endpoint it enumerates shares, `/` here, so the ids
    keep `api_v1_`.
    """
    segments = re.sub(r"\{[\w-]+\}", "", path).strip("/").split("/")
    stem = "_".join(segment.replace("-", "_") for segment in segments if segment) or "root"
    return {f"{stem}_{action}" for action in AUTOMATIC_ACTIONS[method]}


def is_idempotency_key(parameter: Mapping[str, Any]) -> bool:
    return (
        parameter.get("in") == "header"
        and str(parameter.get("name", "")).lower() == "idempotency-key"
    )


def honoured_exemptions(operation: Mapping[str, Any]) -> set[str]:
    """The rules `x-quality-exempt` waives: an exemptable rule with a reason."""
    exempt = operation.get("x-quality-exempt")
    if not isinstance(exempt, dict):
        return set()
    return {
        rule
        for rule, reason in exempt.items()
        if rule in EXEMPTABLE and isinstance(reason, str) and reason.strip()
    }


def takes_data(operation: Mapping[str, Any]) -> bool:
    """A body, a query parameter or a required header: something a caller can get wrong."""
    return bool(operation.get("requestBody")) or any(
        parameter.get("in") == "query"
        or (parameter.get("in") == "header" and parameter.get("required") is True)
        for parameter in operation.get("parameters") or []
    )


def answers_with_problem_details(response: Mapping[str, Any]) -> bool:
    content = response.get("content") or {}
    return bool(content) and all(
        (media.get("schema") or {}).get("$ref") == PROBLEM_DETAILS for media in content.values()
    )


def violations(method: str, path: str, operation: Mapping[str, Any]) -> list[str]:
    """The rules an operation breaks, in `RULES` order."""
    operation_id = str(operation.get("operationId") or "")
    parameters = operation.get("parameters") or []
    declared = operation.get("responses") or {}
    responses = {str(status): answer for status, answer in declared.items()}
    broken = {
        "operation-id": not SNAKE_CASE.fullmatch(operation_id)
        or operation_id in automatic_operation_ids(method, path),
        "summary": not str(operation.get("summary") or "").strip(),
        "description": not str(operation.get("description") or "").strip(),
        # A preview writes nothing, so repeating it needs no key.
        "idempotency-key": method in MUTATIONS
        and operation.get("x-dry-run") is not True
        and not any(is_idempotency_key(p) and p.get("required") is True for p in parameters),
        "error-400": (takes_data(operation) and "400" not in responses)
        or not all(
            answers_with_problem_details(responses[status])
            for status in ("400", "422")
            if status in responses
        ),
    }
    exempt = honoured_exemptions(operation)
    return [rule for rule in RULES if broken[rule] and rule not in exempt]


def contract_problems(document: Document) -> list[str]:
    """What no baseline forgives: a missing ProblemDetails, a numbered duplicate id
    and an exemption that cannot be honoured."""
    found = []
    if "ProblemDetails" not in ((document.get("components") or {}).get("schemas") or {}):
        found.append(
            "Brak komponentu ProblemDetails, na który mają wskazywać odpowiedzi 400 i 422."
        )
    ids = {operation.get("operationId") for _, _, operation in operations(document)}
    for method, path, operation in operations(document):
        key = operation_key(method, path)
        duplicate = DEDUPLICATED.fullmatch(str(operation.get("operationId") or ""))
        if duplicate and duplicate.group(1) in ids:
            found.append(
                f"{key}: operationId {duplicate.group(0)!r} to powtórzony {duplicate.group(1)!r} "
                "z numerem od generatora; nadaj operacji własne operation_id."
            )
        exempt = operation.get("x-quality-exempt")
        if exempt is None:
            continue
        if not isinstance(exempt, dict):
            found.append(f"{key}: x-quality-exempt ma postać {{reguła: powód}}.")
            continue
        for rule, reason in exempt.items():
            if rule not in EXEMPTABLE:
                found.append(
                    f"{key}: x-quality-exempt nie uchyla reguły {rule!r}; uchylić można "
                    f"tylko {', '.join(sorted(EXEMPTABLE))}."
                )
            elif not isinstance(reason, str) or not reason.strip():
                found.append(f"{key}: x-quality-exempt dla {rule!r} wymaga powodu.")
    return found


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def shape(schema: Any, *, inputs: bool) -> Any:
    """What a schema accepts: names, types, formats, enums, nullability, required, bounds.

    Only keywords go: a property called `title` or `description` is a name and
    stays. For inputs a read-only property is nothing the caller sends, so it
    leaves both `properties` and `required`. A `$ref` stays a reference.
    """
    if not isinstance(schema, dict):
        return schema
    reduced: dict[str, Any] = {}
    read_only: set[str] = set()
    for keyword, value in schema.items():
        if keyword == "properties" and isinstance(value, dict):
            read_only = {
                name
                for name, field in value.items()
                if inputs and isinstance(field, dict) and field.get("readOnly") is True
            }
            reduced[keyword] = {
                name: shape(field, inputs=inputs)
                for name, field in value.items()
                if name not in read_only
            }
        elif keyword in SUBSCHEMA_KEYWORDS:
            reduced[keyword] = shape(value, inputs=inputs)
        elif keyword in SUBSCHEMA_LIST_KEYWORDS and isinstance(value, list):
            reduced[keyword] = [shape(item, inputs=inputs) for item in value]
        elif keyword in SHAPE_KEYWORDS:
            reduced[keyword] = value
    if isinstance(schema.get("required"), list):
        reduced["required"] = sorted(name for name in schema["required"] if name not in read_only)
    return reduced


def resolved(document: Document, schema: Any) -> Any:
    """A component reference followed once."""
    reference = schema.get("$ref") if isinstance(schema, dict) else None
    prefix = "#/components/schemas/"
    if isinstance(reference, str) and reference.startswith(prefix):
        components = (document.get("components") or {}).get("schemas") or {}
        return components.get(reference.removeprefix(prefix), schema)
    return schema


def fingerprint(document: Document, method: str, path: str, operation: Mapping[str, Any]) -> str:
    """What an operation takes and what it answers on success, hashed.

    Parameters except Idempotency-Key, as {in, name, required, schema}; the
    request body with its component followed one level, because a field added
    to a serializer is a new input; the 1xx-3xx responses with references left
    unresolved, so an edit inside a component (ProblemDetails, a response
    serializer, an enum one level down the body) moves nothing. Ids, tags,
    documentation, extensions and 4xx/5xx answers are left out.
    """
    parameters = sorted(
        canonical({
            "in": parameter.get("in"),
            "name": parameter.get("name"),
            "required": parameter.get("required") is True,
            "schema": shape(parameter.get("schema"), inputs=True),
        })
        for parameter in operation.get("parameters") or []
        if not is_idempotency_key(parameter)
    )
    body = operation.get("requestBody")
    request = None
    if body:
        request = {
            "required": body.get("required") is True,
            "inputs": sorted({
                canonical(shape(resolved(document, media.get("schema")), inputs=True))
                for media in (body.get("content") or {}).values()
            }),
        }
    responses = {
        str(status): sorted({
            canonical(shape(media.get("schema"), inputs=False))
            for media in (answer.get("content") or {}).values()
        })
        for status, answer in (operation.get("responses") or {}).items()
        if str(status)[:1] in {"1", "2", "3"}
    }
    taken = {
        "method": method,
        "path": path,
        "parameters": parameters,
        "requestBody": request,
        "responses": responses,
    }
    return hashlib.sha256(canonical(taken).encode()).hexdigest()[:16]


def audit(document: Document) -> Audit:
    return {
        operation_key(method, path): {
            "fingerprint": fingerprint(document, method, path, operation),
            "violations": violations(method, path, operation),
        }
        for method, path, operation in operations(document)
    }


def empty_baseline() -> Baseline:
    return {"version": 1, "rules": list(RULES), "operations": {}}


def floor_problems(
    document: Document,
    core: Baseline | None,
    product: Baseline | None = None,
    *,
    in_product: bool = False,
) -> list[str]:
    """Everything the floor refuses in a contract, given its baselines.

    The owned baseline — the core's, or in a product repository the product's
    own — must not keep an operation that is gone or a violation that is fixed.
    In a product the core's baseline only forgives: it cannot be edited there,
    and an operation the product leaves out is not the product's debt.
    """
    found = contract_problems(document)
    if not in_product and core is None:
        return [*found, f"Brak pliku {CORE_BASELINE}: utwórz go przez {WRITE}."]
    owned = (product or empty_baseline()) if in_product else (core or empty_baseline())
    if owned.get("version") != 1:
        found.append(f"Nieznana wersja linii bazowej: {owned.get('version')!r}, oczekiwana 1.")
    if owned.get("rules") != list(RULES):
        found.append(
            f"Linia bazowa obejmuje reguły {owned.get('rules')}, a podłoga sprawdza {list(RULES)}. "
            f"Wycofaną regułę usuwa {WRITE}; nowa reguła wymaga linii bazowej od nowa "
            f"(usuń plik i uruchom {WRITE}) w osobnym commicie."
        )
    forgiven = owned["operations"]
    if in_product:
        forgiven = {**(core or empty_baseline())["operations"], **forgiven}
    current = audit(document)
    for key, now in current.items():
        entry = forgiven.get(key)
        broken = ", ".join(now["violations"])
        if not broken:
            continue
        if entry is None:
            found.append(f"{key}: nowa operacja łamie {broken}.")
        elif entry["fingerprint"] != now["fingerprint"]:
            found.append(
                f"{key}: operacja się zmieniła (odcisk {entry['fingerprint']} → "
                f"{now['fingerprint']}), więc traci uchylenia; łamie {broken}."
            )
        elif new := [rule for rule in now["violations"] if rule not in entry["violations"]]:
            found.append(f"{key}: nowe naruszenie {', '.join(new)}.")
    for key, entry in owned["operations"].items():
        if key not in current:
            found.append(f"{key}: operacji już nie ma w kontrakcie; usuń wpis przez {WRITE}.")
        elif fixed := [
            rule for rule in entry["violations"] if rule not in current[key]["violations"]
        ]:
            found.append(
                f"{key}: naprawione {', '.join(fixed)}; zmniejsz linię bazową przez {WRITE}."
            )
    if in_product and product is None and found:
        found.append(
            f"Produkt nie ma jeszcze {PRODUCT_BASELINE}: dług własnych operacji zapisz raz "
            f"przez {WRITE}."
        )
    return found


def shrunk(baseline: Baseline, current: Audit) -> Baseline:
    """The baseline without what is gone or fixed.

    It never adds an operation or a rule and never moves a fingerprint, so a
    new or changed operation stays refused until it meets the floor.
    """
    kept = {}
    for key, entry in baseline["operations"].items():
        now = current.get(key, {}).get("violations", [])
        still = [rule for rule in RULES if rule in entry["violations"] and rule in now]
        if still:
            kept[key] = {"fingerprint": entry["fingerprint"], "violations": still}
    rules = [rule for rule in RULES if rule in baseline["rules"]]
    return {"version": 1, "rules": rules, "operations": kept}


def created(current: Audit, forgiven: Mapping[str, Any] | None = None) -> Baseline:
    """Today's debt, less what `forgiven` (in a product: the core's baseline) covers."""

    def covered(key: str, now: Mapping[str, Any]) -> bool:
        entry = (forgiven or {}).get(key)
        return (
            entry is not None
            and entry["fingerprint"] == now["fingerprint"]
            and set(now["violations"]) <= set(entry["violations"])
        )

    return {
        **empty_baseline(),
        "operations": {
            key: now for key, now in current.items() if now["violations"] and not covered(key, now)
        },
    }


def dumps(baseline: Baseline) -> str:
    """Sorted, one operation per line, so branches that pay down debt merge cleanly."""
    lines = [
        f"    {json.dumps(key)}: {json.dumps(entry)}"
        for key, entry in sorted(baseline["operations"].items())
    ]
    operations_ = "{\n" + ",\n".join(lines) + "\n  }" if lines else "{}"
    return (
        "{\n"
        f'  "version": {json.dumps(baseline["version"])},\n'
        f'  "rules": {json.dumps(baseline["rules"])},\n'
        f'  "operations": {operations_}\n'
        "}\n"
    )


def read_baseline(path: Path) -> Baseline | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_contract(repository: Path) -> dict[str, Any]:
    return yaml.safe_load((repository / CONTRACT).read_text(encoding="utf-8"))


def repository_problems(repository: Path) -> list[str]:
    in_product = (repository / UPSTREAM_MARKER).exists()
    return floor_problems(
        load_contract(repository),
        read_baseline(repository / CORE_BASELINE),
        read_baseline(repository / PRODUCT_BASELINE) if in_product else None,
        in_product=in_product,
    )


def write_baseline(repository: Path) -> Path:
    """Shrink the owned baseline, or create it from today's debt when it is absent."""
    in_product = (repository / UPSTREAM_MARKER).exists()
    target = repository / (PRODUCT_BASELINE if in_product else CORE_BASELINE)
    current = audit(load_contract(repository))
    existing = read_baseline(target)
    if existing is not None:
        baseline = shrunk(existing, current)
    else:
        core = read_baseline(repository / CORE_BASELINE) if in_product else None
        baseline = created(current, (core or empty_baseline())["operations"])
    target.write_text(dumps(baseline), encoding="utf-8")
    return target


def debt_line(current: Audit) -> str:
    per_rule = Counter(rule for now in current.values() for rule in now["violations"])
    indebted = sum(1 for now in current.values() if now["violations"])
    rules = ", ".join(f"{rule} {per_rule[rule]}" for rule in RULES)
    return (
        f"Dług podłogi OpenAPI: operacje {len(current)}, z naruszeniami {indebted}; "
        f"{rules} (razem {sum(per_rule.values())})."
    )


def main(argv: list[str] | None = None, repository: Path = REPOSITORY) -> int:
    parser = argparse.ArgumentParser(
        description="Podłoga jakości OpenAPI (ADR-076 §7) dla nowych i zmienionych operacji."
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="zmniejsz linię bazową długu albo utwórz ją, gdy jej nie ma",
    )
    arguments = parser.parse_args(argv)
    if arguments.write_baseline:
        print(f"Zapisano {write_baseline(repository).relative_to(repository)}.")
    print(debt_line(audit(load_contract(repository))))
    found = repository_problems(repository)
    if found:
        print("Podłoga OpenAPI nie przechodzi:", file=sys.stderr)
        for problem in found:
            print(f"- {problem}", file=sys.stderr)
    return 1 if found else 0


# The gate and the engine's own tests. Synthetic contracts are written the way
# drf-spectacular writes them.

PATH = "/api/v1/farms/{farm_id}/visits/"
KEY = f"POST {PATH}"
PROBLEM_RESPONSE = {
    "content": {"application/json": {"schema": {"$ref": PROBLEM_DETAILS}}},
    "description": "",
}


def visits_contract() -> dict[str, Any]:
    """One mutation that meets the floor."""
    visit_input = {"$ref": "#/components/schemas/VisitInput"}
    visit = {"$ref": "#/components/schemas/Visit"}
    return copy.deepcopy({
        "openapi": "3.1.0",
        "paths": {
            PATH: {
                "post": {
                    "operationId": "farm_visits_create",
                    "summary": "Plan a visit",
                    "description": "Plans a trimming visit on the farm.",
                    "tags": ["farms"],
                    "parameters": [
                        {
                            "in": "path",
                            "name": "farm_id",
                            "required": True,
                            "schema": {"type": "string", "format": "uuid"},
                        },
                        {
                            "in": "header",
                            "name": "Idempotency-Key",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                    ],
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": visit_input},
                            "multipart/form-data": {"schema": copy.deepcopy(visit_input)},
                        },
                        "required": True,
                    },
                    "responses": {
                        "201": {
                            "content": {"application/json": {"schema": visit}},
                            "description": "",
                        },
                        "400": PROBLEM_RESPONSE,
                    },
                },
            },
        },
        "components": {
            "schemas": {
                "ProblemDetails": {
                    "type": "object",
                    "properties": {"code": {"type": "string"}, "detail": {}},
                    "required": ["code", "detail"],
                },
                "VisitInput": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "format": "uuid", "readOnly": True},
                        "title": {"type": "string", "maxLength": 120},
                        "planned_on": {"type": "string", "format": "date"},
                        "kind": {"$ref": "#/components/schemas/KindEnum"},
                    },
                    "required": ["id", "planned_on", "title"],
                },
                "KindEnum": {"enum": ["trim", "check"], "type": "string"},
                "Visit": {
                    "type": "object",
                    "properties": {"id": {"type": "string", "format": "uuid"}},
                    "required": ["id"],
                },
            },
        },
    })


def visit_operation(document: Document) -> dict[str, Any]:
    return document["paths"][PATH]["post"]


def visit_fingerprint(document: Document) -> str:
    return fingerprint(document, "post", PATH, visit_operation(document))


def repository_with(root: Path, document: Document, *, core: Baseline | None = None) -> Path:
    (root / CONTRACT).parent.mkdir(parents=True)
    (root / CONTRACT).write_text(yaml.safe_dump(dict(document)), encoding="utf-8")
    if core is not None:
        (root / CORE_BASELINE).write_text(dumps(core), encoding="utf-8")
    return root


def test_the_committed_contract_keeps_the_floor() -> None:
    found = repository_problems(REPOSITORY)

    assert found == [], "Podłoga OpenAPI (ADR-076 §7):\n" + "\n".join(found)


def test_automatic_operation_ids_are_recognised() -> None:
    assert "api_v1_booking_places_retrieve" in automatic_operation_ids(
        "get", "/api/v1/booking/places/"
    )
    place = "/api/v1/booking/appointments/{appointment_id}/place/"
    assert automatic_operation_ids("put", place) == {
        "api_v1_booking_appointments_place_update"
    }
    assert automatic_operation_ids("post", "/api/v1/auth/email-verifications/confirm/") == {
        "api_v1_auth_email_verifications_confirm_create"
    }
    assert "farms_list" not in automatic_operation_ids("get", "/api/v1/farms/")

    operation = visit_operation(visits_contract())
    for operation_id, refused in (
        ("api_v1_farms_visits_create", True),
        ("farmVisitsCreate", True),
        ("", True),
        ("farm_visits_create", False),
    ):
        operation["operationId"] = operation_id
        assert ("operation-id" in violations("post", PATH, operation)) is refused, operation_id


def test_a_400_answers_whatever_takes_data_and_every_400_and_422_is_problem_details() -> None:
    path = "/api/v1/farms/"
    operation: dict[str, Any] = {
        "operationId": "farms_list",
        "summary": "Farms",
        "description": "Lists the organization's farms.",
        "parameters": [{"in": "header", "name": "If-None-Match", "schema": {"type": "string"}}],
        "responses": {"200": {"description": ""}},
    }
    assert violations("get", path, operation) == []

    for data in (
        {"in": "query", "name": "active", "schema": {"type": "boolean"}},
        {"in": "header", "name": "webhook-id", "required": True, "schema": {"type": "string"}},
    ):
        assert violations("get", path, operation | {"parameters": [data]}) == ["error-400"]
    operation["parameters"] = [{"in": "query", "name": "active", "schema": {"type": "boolean"}}]
    operation["responses"]["400"] = PROBLEM_RESPONSE
    assert violations("get", path, operation) == []

    for answer in (
        {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Farm"}}}},
        {"description": "No body."},
    ):
        for status in ("400", "422"):
            responses = operation["responses"] | {status: answer}
            assert violations("get", path, operation | {"responses": responses}) == ["error-400"]


def test_a_dry_run_needs_no_idempotency_key() -> None:
    operation = visit_operation(visits_contract())
    operation["parameters"].pop()
    assert violations("post", PATH, operation) == ["idempotency-key"]

    operation["x-dry-run"] = True
    assert violations("post", PATH, operation) == []
    del operation["summary"]
    assert violations("post", PATH, operation) == ["summary"]


def test_an_exemption_needs_a_reason_and_covers_only_idempotency_and_400() -> None:
    document = visits_contract()
    operation = visit_operation(document)
    operation["parameters"].pop()
    del operation["responses"]["400"], operation["summary"]
    assert violations("post", PATH, operation) == ["summary", "idempotency-key", "error-400"]

    operation["x-quality-exempt"] = {
        "idempotency-key": "Planning the same visit twice changes nothing.",
        "error-400": "  ",
        "summary": "Obvious from the path.",
    }

    assert violations("post", PATH, operation) == ["summary", "error-400"]
    assert contract_problems(document) == [
        f"{KEY}: x-quality-exempt dla 'error-400' wymaga powodu.",
        f"{KEY}: x-quality-exempt nie uchyla reguły 'summary'; uchylić można tylko "
        "error-400, idempotency-key.",
    ]


def test_a_numbered_duplicate_id_or_no_problem_details_is_never_forgiven() -> None:
    document = visits_contract()
    trims = "/api/v1/farms/{farm_id}/trims/"
    document["paths"][trims] = {
        "post": visit_operation(document) | {"operationId": "farm_visits_create_2"}
    }

    assert contract_problems(document) == [
        f"POST {trims}: operationId 'farm_visits_create_2' to powtórzony 'farm_visits_create' "
        "z numerem od generatora; nadaj operacji własne operation_id."
    ]

    document["paths"][trims]["post"]["operationId"] = "farm_trims_create"
    del document["components"]["schemas"]["ProblemDetails"]
    assert contract_problems(document) == [
        "Brak komponentu ProblemDetails, na który mają wskazywać odpowiedzi 400 i 422."
    ]


def test_fingerprint_ignores_documentation_ids_tags_extensions_4xx_and_idempotency_key() -> None:
    document = visits_contract()
    before = visit_fingerprint(document)
    operation = visit_operation(document)
    operation.update(
        operationId="farm_visits_plan",
        summary="Plan a trimming visit",
        description="Other words.",
        tags=["visits"],
    )
    operation["x-quality-exempt"] = {"error-400": "Nothing to get wrong."}
    operation["parameters"] = [operation["parameters"][0] | {"description": "The farm."}]
    operation["responses"]["400"] = {"description": ""}
    operation["responses"]["409"] = PROBLEM_RESPONSE
    visit_input = document["components"]["schemas"]["VisitInput"]
    visit_input["description"] = "A visit to plan."
    visit_input["properties"]["title"] |= {
        "title": "Title",
        "description": "What the visit is for.",
        "example": "Spring trim",
    }
    visit_input["properties"]["created_at"] = {
        "type": "string",
        "format": "date-time",
        "readOnly": True,
    }
    visit_input["required"].append("created_at")

    assert visit_fingerprint(document) == before


def test_fingerprint_changes_with_a_parameter_a_body_or_a_success_response() -> None:
    before = visit_fingerprint(visits_contract())
    changes: dict[str, Callable[[dict[str, Any]], object]] = {
        "a query parameter": lambda operation: operation["parameters"].append({
            "in": "query",
            "name": "notify",
            "schema": {"type": "boolean"},
        }),
        "a parameter's format": lambda operation: operation["parameters"][0]["schema"].update(
            format="slug"
        ),
        "an optional body": lambda operation: operation["requestBody"].update(required=False),
        "another body": lambda operation: operation["requestBody"]["content"].update({
            "application/json": {"schema": {"$ref": "#/components/schemas/Visit"}}
        }),
        "another success status": lambda operation: operation["responses"].update({
            "200": operation["responses"].pop("201")
        }),
        "another success body": lambda operation: operation["responses"]["201"].update(
            content={"application/json": {"schema": {"$ref": "#/components/schemas/VisitInput"}}}
        ),
    }

    unchanged = []
    for name, change in changes.items():
        document = visits_contract()
        change(visit_operation(document))
        if visit_fingerprint(document) == before:
            unchanged.append(name)
    assert unchanged == []


def test_a_new_input_field_marks_the_operation_changed() -> None:
    """64cd0b3 added place_town and place_address to AppointmentCreate only.

    Inputs grow in a serializer, not in the operation, so the request body's
    component counts, one level deep. A property named like a keyword
    (`title`) is a name, not documentation.
    """
    before = visit_fingerprint(visits_contract())
    changes: list[Callable[[dict[str, Any]], object]] = [
        lambda schema: schema["properties"].update(place_town={"type": "string", "maxLength": 120}),
        lambda schema: schema["properties"].pop("title"),
        lambda schema: schema["properties"]["title"].update(maxLength=200),
        lambda schema: schema["properties"]["title"].update(type=["string", "null"]),
        lambda schema: schema["required"].remove("title"),
        lambda schema: schema["properties"]["kind"].update({"$ref": "#/components/schemas/Visit"}),
    ]

    for number, change in enumerate(changes):
        document = visits_contract()
        change(document["components"]["schemas"]["VisitInput"])
        assert visit_fingerprint(document) != before, number


def test_edits_behind_a_reference_mark_nothing() -> None:
    document = visits_contract()
    before = visit_fingerprint(document)
    schemas = document["components"]["schemas"]
    schemas["KindEnum"]["enum"].append("treatment")
    schemas["Visit"]["properties"]["acting"] = {"type": "string"}
    schemas["ProblemDetails"]["properties"]["errors"] = {"type": "array"}

    assert visit_fingerprint(document) == before


def test_a_problem_details_change_marks_no_operation_of_the_contract() -> None:
    document = load_contract(REPOSITORY)
    before = {key: now["fingerprint"] for key, now in audit(document).items()}
    problem = document["components"]["schemas"]["ProblemDetails"]
    problem["properties"]["hint"] = {"type": "string", "maxLength": 200}
    problem["required"].append("hint")

    assert {key: now["fingerprint"] for key, now in audit(document).items()} == before


def test_a_new_operation_must_meet_every_rule() -> None:
    document = visits_contract()
    assert floor_problems(document, empty_baseline()) == []

    operation = visit_operation(document)
    operation["operationId"] = "api_v1_farms_visits_create"
    del operation["summary"], operation["description"], operation["responses"]["400"]
    operation["parameters"].pop()

    assert floor_problems(document, empty_baseline()) == [
        f"{KEY}: nowa operacja łamie operation-id, summary, description, idempotency-key, "
        "error-400."
    ]


def test_a_changed_operation_loses_its_grandfathered_rules() -> None:
    document = visits_contract()
    del visit_operation(document)["summary"]
    baseline = created(audit(document))
    assert floor_problems(document, baseline) == []

    document["components"]["schemas"]["VisitInput"]["properties"]["place_town"] = {"type": "string"}
    old, new = baseline["operations"][KEY]["fingerprint"], visit_fingerprint(document)

    assert floor_problems(document, baseline) == [
        f"{KEY}: operacja się zmieniła (odcisk {old} → {new}), więc traci uchylenia; łamie summary."
    ]


def test_a_new_violation_on_an_unchanged_operation_fails() -> None:
    document = visits_contract()
    del visit_operation(document)["summary"]
    baseline = created(audit(document))
    del visit_operation(document)["description"]

    assert floor_problems(document, baseline) == [f"{KEY}: nowe naruszenie description."]


def test_stale_entries_fail_and_writing_only_shrinks() -> None:
    document = visits_contract()
    del visit_operation(document)["summary"], visit_operation(document)["description"]
    baseline = created(audit(document))
    gone = "DELETE /api/v1/farms/{farm_id}/"
    baseline["operations"][gone] = {"fingerprint": "0" * 16, "violations": ["summary"]}
    visit_operation(document)["description"] = "Plans a trimming visit on the farm."

    assert floor_problems(document, baseline) == [
        f"{KEY}: naprawione description; zmniejsz linię bazową przez {WRITE}.",
        f"{gone}: operacji już nie ma w kontrakcie; usuń wpis przez {WRITE}.",
    ]

    smaller = shrunk(baseline, audit(document))
    assert smaller["operations"] == {
        KEY: {"fingerprint": baseline["operations"][KEY]["fingerprint"], "violations": ["summary"]}
    }
    assert floor_problems(document, smaller) == []

    # Neither a new operation nor a changed one gets in by writing.
    document["paths"]["/api/v1/farms/"] = {
        "get": {"operationId": "api_v1_farms_list", "responses": {"200": {"description": ""}}}
    }
    document["components"]["schemas"]["VisitInput"]["properties"]["place_town"] = {"type": "string"}
    assert shrunk(smaller, audit(document)) == smaller
    assert len(floor_problems(document, smaller)) == 2


def test_the_command_creates_an_absent_baseline_and_prints_the_debt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = visits_contract()
    del visit_operation(document)["summary"]
    repository_with(tmp_path, document)

    assert main([], repository=tmp_path) == 1
    assert f"Brak pliku {CORE_BASELINE}" in capsys.readouterr().err

    assert main(["--write-baseline"], repository=tmp_path) == 0
    printed = capsys.readouterr().out
    assert f"Zapisano {CORE_BASELINE}." in printed
    assert (
        "Dług podłogi OpenAPI: operacje 1, z naruszeniami 1; operation-id 0, summary 1, "
        "description 0, idempotency-key 0, error-400 0 (razem 1)."
    ) in printed
    written = json.loads((tmp_path / CORE_BASELINE).read_text(encoding="utf-8"))
    assert written["operations"] == {KEY: audit(document)[KEY]}


def test_a_product_reads_and_writes_its_own_baseline(tmp_path: Path) -> None:
    document = visits_contract()
    del visit_operation(document)["summary"]
    core = created(audit(document))
    # The core also forgives an operation this product does not compose.
    core["operations"]["GET /api/v1/inventory/"] = {
        "fingerprint": "0" * 16,
        "violations": ["summary"],
    }
    herds = "/api/v1/trimming/herds/"
    document["paths"][herds] = {
        "get": {
            "operationId": "api_v1_trimming_herds_list",
            "responses": {"200": {"description": ""}},
        }
    }
    repository_with(tmp_path, document, core=core)
    (tmp_path / UPSTREAM_MARKER).write_text("c17e5bc\n", encoding="utf-8")

    assert repository_problems(tmp_path) == [
        f"GET {herds}: nowa operacja łamie operation-id, summary, description.",
        f"Produkt nie ma jeszcze {PRODUCT_BASELINE}: dług własnych operacji zapisz raz "
        f"przez {WRITE}.",
    ]

    core_file = (tmp_path / CORE_BASELINE).read_text(encoding="utf-8")
    assert write_baseline(tmp_path) == tmp_path / PRODUCT_BASELINE

    assert (tmp_path / CORE_BASELINE).read_text(encoding="utf-8") == core_file
    product = json.loads((tmp_path / PRODUCT_BASELINE).read_text(encoding="utf-8"))
    assert list(product["operations"]) == [f"GET {herds}"]
    assert repository_problems(tmp_path) == []


if __name__ == "__main__":
    sys.exit(main())
