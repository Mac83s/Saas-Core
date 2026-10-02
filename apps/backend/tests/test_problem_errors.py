"""Problem Details name what a caller can fix (ADR-076 §5).

A 400 or a 422 keeps every member it had and adds `errors`: one
`{field, code, message}` per problem, `field` a dotted path into the request
data (list positions as numbers, null for the request as a whole). Only a
`ValidationError` is read as the shape of the input; any other exception is one
refusal. No database: the builder is a pure function, the handler only shapes
a response.
"""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.http import Http404
from django.urls import get_resolver
from rest_framework import serializers
from rest_framework.exceptions import (
    APIException,
    ErrorDetail,
    NotFound,
    ParseError,
    PermissionDenied,
    ValidationError,
)
from rest_framework.response import Response

from saas_core.http.exceptions import (
    problem_code,
    problem_details_exception_handler,
    problem_errors,
)
from saas_core.modules.shared.sites.change_sets import ChangeSetCommandUnsupported

OLD_MEMBERS = ["type", "title", "status", "code", "detail", "correlation_id"]
TITLE = "Żądanie nie może zostać obsłużone"


class Address(serializers.Serializer):
    city = serializers.CharField(max_length=3)


class Item(serializers.Serializer):
    name = serializers.CharField()
    qty = serializers.IntegerField(min_value=1)


class Order(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(required=False)
    address = Address()
    items = Item(many=True)
    tags = serializers.ListField(child=serializers.IntegerField())
    slots = serializers.DictField(child=serializers.CharField(max_length=2))

    def validate_password(self, value: str) -> str:
        validate_password(value)
        return value


class WholeOrder(serializers.Serializer):
    quantity = serializers.IntegerField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        raise ValidationError("Zamówienie jako całość jest sprzeczne.", code="order_contradictory")


VALID_ORDER = {
    "email": "jan@example.com",
    "address": {"city": "Ełk"},
    "items": [{"name": "siano", "qty": 1}],
    "tags": [1],
    "slots": {"rano": "ok"},
}


class SlotTaken(APIException):
    status_code = 400
    default_code = "slot_taken"
    default_detail = "Termin jest zajęty."


class StartTaken(SlotTaken):
    problem_field = "starts_at"


class LocaleUnitInvalid(ValidationError):
    problem_code = "locale_unit_invalid"


def rejected(serializer_class: type[serializers.Serializer], data: Any) -> ValidationError:
    serializer = serializer_class(data=data)
    with pytest.raises(ValidationError) as raised:
        serializer.is_valid(raise_exception=True)
    return raised.value


def pairs(entries: list[dict[str, Any]]) -> set[tuple[Any, Any]]:
    return {(entry["field"], entry["code"]) for entry in entries}


def handle(exc: Exception, request: Any = None) -> Response:
    response = problem_details_exception_handler(exc, {"request": request})
    assert response is not None
    return response


def test_a_field_error_names_the_field_and_its_own_code() -> None:
    order = {key: value for key, value in VALID_ORDER.items() if key != "tags"}
    exc = rejected(Order, {**order, "email": "nie-adres"})

    entries = problem_errors(exc)

    assert pairs(entries) == {("email", "invalid"), ("tags", "required")}
    assert all(isinstance(entry["message"], str) and entry["message"] for entry in entries)
    assert problem_code(exc) == "invalid"


def test_nested_and_listed_inputs_are_dot_paths_with_numeric_indexes() -> None:
    exc = rejected(
        Order,
        {
            **VALID_ORDER,
            "address": {"city": "Warszawa"},
            "items": [{"name": "siano", "qty": 1}, {"qty": 0}],
            "tags": [1, "dwa"],
            "slots": {"/0/data/title": "za długie"},
        },
    )

    assert pairs(problem_errors(exc)) == {
        ("address.city", "max_length"),
        ("items.1.name", "required"),
        ("items.1.qty", "min_value"),
        ("tags.1", "invalid"),
        ("slots./0/data/title", "max_length"),
    }


def test_a_django_validator_keeps_its_own_codes() -> None:
    exc = rejected(Order, {**VALID_ORDER, "password": "12345"})

    assert pairs(problem_errors(exc)) >= {
        ("password", "password_too_short"),
        ("password", "password_entirely_numeric"),
    }


def test_request_level_errors_have_no_field_and_nested_ones_name_their_parent() -> None:
    whole = rejected(WholeOrder, {"quantity": 1})
    not_a_list = rejected(Order, {**VALID_ORDER, "items": "siano"})
    model = ValidationError({"__all__": ["Ten okres nachodzi na inny."], "slug": ["Zajęty."]})

    assert problem_errors(whole) == [
        {
            "field": None,
            "code": "order_contradictory",
            "message": "Zamówienie jako całość jest sprzeczne.",
        }
    ]
    assert pairs(problem_errors(not_a_list)) == {("items", "not_a_list")}
    # Django's own non-field key, as a model's `message_dict` carries it.
    assert pairs(problem_errors(model)) == {(None, "invalid"), ("slug", "invalid")}


def test_a_code_given_to_validation_error_reaches_its_entries_not_the_top_level() -> None:
    taken = ValidationError({"slug": "Ten adres jest zajęty."}, code="slug_taken")
    unknown = ValidationError("Nieznany rodzaj.", code="unknown_kind")

    assert problem_errors(taken) == [
        {"field": "slug", "code": "slug_taken", "message": "Ten adres jest zajęty."}
    ]
    assert problem_errors(unknown) == [
        {"field": None, "code": "unknown_kind", "message": "Nieznany rodzaj."}
    ]
    assert handle(taken).data["code"] == handle(unknown).data["code"] == "invalid"


def test_a_validation_error_subclass_names_a_domain_code_at_the_top() -> None:
    exc = LocaleUnitInvalid({
        "units": {"0/data/title": [ErrorDetail("Brak znacznika w tytule.", code="token_missing")]}
    })

    response = handle(exc)

    assert (response.status_code, response.data["code"]) == (400, "locale_unit_invalid")
    assert response.data["errors"] == [
        {
            "field": "units.0/data/title",
            "code": "token_missing",
            "message": "Brak znacznika w tytule.",
        }
    ]


def test_a_domain_refusal_is_one_entry_with_its_code_and_optional_field() -> None:
    assert problem_errors(SlotTaken()) == [
        {"field": None, "code": "slot_taken", "message": "Termin jest zajęty."}
    ]
    assert problem_errors(StartTaken("Ten termin właśnie zajęto.")) == [
        {"field": "starts_at", "code": "slot_taken", "message": "Ten termin właśnie zajęto."}
    ]
    assert problem_errors(SlotTaken("Termin minął.", code="slot_past")) == [
        {"field": None, "code": "slot_past", "message": "Termin minął."}
    ]
    # DRF's own refusal of a body it cannot parse.
    assert problem_errors(ParseError("Zły JSON.")) == [
        {"field": None, "code": "parse_error", "message": "Zły JSON."}
    ]


def test_a_refusal_carrying_its_own_dict_is_still_one_entry() -> None:
    """Only a `ValidationError` is the input's shape: a module's own dict in an
    other exception's detail is not walked into fields the request never had."""
    detail = {
        "message": "Tłumaczenie ma błędne jednostki.",
        "errors": [{"field": "units.1/text", "code": "too_long"}],
    }

    class UnitsRefused(APIException):
        status_code = 422
        default_code = "locale_unit_invalid"
        default_detail = "Jednostki tłumaczenia są nieprawidłowe."

    response = handle(UnitsRefused(detail))

    assert response.data["detail"] == detail
    assert response.data["errors"] == [
        {
            "field": None,
            "code": "locale_unit_invalid",
            "message": "Jednostki tłumaczenia są nieprawidłowe.",
        }
    ]


def test_a_content_operations_422_keeps_status_code_and_detail_and_gains_one_entry() -> None:
    message = "Komenda page.publish wymaga osobnej operacji."

    response = handle(ChangeSetCommandUnsupported(detail=message))

    assert response.status_code == 422
    assert response.data["code"] == "change_set_command_unsupported"
    assert response.data["detail"] == message
    assert response.data["errors"] == [
        {"field": None, "code": "change_set_command_unsupported", "message": message}
    ]


def test_other_statuses_carry_no_errors() -> None:
    class Conflict(APIException):
        status_code = 409
        default_code = "version_conflict"
        default_detail = "Ktoś zmienił ten zasób."

    refusals = ((PermissionDenied(), 403), (NotFound(), 404), (Http404(), 404), (Conflict(), 409))
    for exc, status in refusals:
        response = handle(exc)
        assert response.status_code == status
        assert list(response.data) == OLD_MEMBERS


def test_existing_members_are_unchanged() -> None:
    request = SimpleNamespace(correlation_id="0199a3f0-7c1e-7d4a-9b2f-3e5a6c7d8e9f")
    expected = {"type": "about:blank", "title": TITLE, "correlation_id": request.correlation_id}

    validation = handle(ValidationError({"email": ["Zły adres."]}), request)
    parse = handle(ParseError("Brak nagłówka Idempotency-Key."), request)
    refusal = handle(ChangeSetCommandUnsupported(), request)

    for response in (validation, parse, refusal):
        assert list(response.data) == [*OLD_MEMBERS, "errors"]
        assert response.content_type == "application/problem+json"
    assert {key: validation.data[key] for key in OLD_MEMBERS} == {
        **expected,
        "status": 400,
        "code": "invalid",
        "detail": {"email": ["Zły adres."]},
    }
    assert {key: parse.data[key] for key in OLD_MEMBERS} == {
        **expected,
        "status": 400,
        "code": "parse_error",
        "detail": "Brak nagłówka Idempotency-Key.",
    }
    assert {key: refusal.data[key] for key in OLD_MEMBERS} == {
        **expected,
        "status": 422,
        "code": "change_set_command_unsupported",
        "detail": "Ta komenda nie jest wykonywana przez change set.",
    }


def test_a_detail_keyed_dict_keeps_every_entry_in_errors() -> None:
    response = handle(ValidationError({"detail": "Zły.", "other": ["Też zły."]}))

    # The old member unwraps `detail` and drops the rest; `errors` keeps both.
    assert response.data["detail"] == "Zły."
    assert response.data["errors"] == [
        {"field": "detail", "code": "invalid", "message": "Zły."},
        {"field": "other", "code": "invalid", "message": "Też zły."},
    ]


def _subclasses(cls: type[APIException]) -> Iterator[type[APIException]]:
    for subclass in cls.__subclasses__():
        yield subclass
        yield from _subclasses(subclass)


def test_every_400_and_422_exception_class_answers_non_empty_errors() -> None:
    assert get_resolver().url_patterns  # imports every mounted view, and what it raises
    classes = sorted(
        {
            cls
            for cls in _subclasses(APIException)
            if cls.__module__.startswith("saas_core.") and cls.status_code in {400, 422}
        },
        key=lambda cls: (cls.__module__, cls.__qualname__),
    )

    assert classes
    for cls in classes:
        try:
            exc = cls()
        except TypeError:  # a constructor that wants the case's own values
            exc = cls.__new__(cls)
            APIException.__init__(exc)
        response = handle(exc)
        errors = response.data["errors"]
        assert errors, cls
        if not isinstance(exc, ValidationError):
            assert len(errors) == 1, cls
            assert errors[0]["code"] == response.data["code"], cls


def test_the_contract_declares_errors_as_an_optional_list_of_field_errors() -> None:
    contract_path = Path(settings.SITE_BLOCK_CONTRACTS_PATH).parent / "openapi" / "v1.yaml"
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    contract = yaml.load(contract_path.read_text(encoding="utf-8"), Loader=loader)
    schemas = contract["components"]["schemas"]

    problem = schemas["ProblemDetails"]
    assert sorted(problem["required"]) == sorted(OLD_MEMBERS)
    assert problem["properties"]["errors"]["type"] == "array"
    assert problem["properties"]["errors"]["items"] == {
        "$ref": "#/components/schemas/ProblemFieldError"
    }
    field_error = schemas["ProblemFieldError"]
    assert sorted(field_error["required"]) == ["code", "field", "message"]
    assert field_error["properties"]["field"]["type"] == ["string", "null"]
    assert all(property_["description"] for property_ in field_error["properties"].values())
