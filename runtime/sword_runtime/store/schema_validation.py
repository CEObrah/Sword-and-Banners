"""Formal registered-schema validation for staged transaction after-images."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping

import jsonschema

from sword_runtime.store.overlay import StagedOverlay
from sword_runtime.store.repository import RepositoryStore


def _objects(value: Any) -> Iterator[Mapping[str, Any]]:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


class RegisteredSchemaValidator:
    """Validate every schema-bearing staged JSON object against the registry.

    Domain validators still own causal, reference, information, and
    conservation rules. This layer makes it impossible for a production
    transaction to rely on those callbacks while silently skipping the formal
    JSON shape registered by the repository.
    """

    def __init__(
        self,
        repository: RepositoryStore,
        *,
        registry_path: str = "game/schemas/registry.json",
    ) -> None:
        registry = repository.read_json(registry_path)
        if not isinstance(registry, Mapping) or not registry:
            raise ValueError("schema registry is missing or invalid")
        normalized: Dict[str, str] = {}
        validators: Dict[str, jsonschema.protocols.Validator] = {}
        validator_classes: Dict[str, type] = {}
        documents: Dict[str, Mapping[str, Any]] = {}
        for schema_id, filename in registry.items():
            if (
                not isinstance(schema_id, str)
                or not schema_id
                or not isinstance(filename, str)
                or not filename
                or Path(filename).name != filename
                or not filename.endswith(".json")
            ):
                raise ValueError("schema registry contains an invalid entry")
            document = repository.read_json("game/schemas/" + filename)
            if not isinstance(document, Mapping):
                raise ValueError(f"registered schema is invalid: {schema_id}")
            validator_class = jsonschema.validators.validator_for(document)
            # Full meta-schema checking is intentionally lazy. A release contains
            # hundreds of registered schemas, while a single transaction usually
            # stages only a handful of schema-bearing records. Checking every
            # schema on every planner construction made cold previews spend seconds
            # validating unrelated static documents. We still fail closed: the
            # first staged use of a schema validates the schema itself before the
            # instance record is accepted. Release validation remains responsible
            # for eagerly checking the complete registry.
            normalized[schema_id] = filename
            validator_classes[schema_id] = validator_class
            documents[schema_id] = document
            validators[schema_id] = validator_class(document)
        self.registry = normalized
        self.validators = validators
        self._validator_classes = validator_classes
        self._documents = documents
        self._schema_checked: set[str] = set()

    @classmethod
    def optional(cls, repository: RepositoryStore) -> "RegisteredSchemaValidator | None":
        if repository.read_optional_bytes("game/schemas/registry.json") is None:
            return None
        return cls(repository)

    def validate_overlay(
        self,
        overlay: StagedOverlay,
        changed_paths: Iterable[str],
    ) -> None:
        for path in sorted(set(changed_paths)):
            if not path.endswith(".json"):
                continue
            if overlay.read_optional_bytes(path) is None:
                continue
            value = overlay.read_json(path)
            if path.startswith("state/") and (
                not isinstance(value, Mapping)
                or not isinstance(value.get("schema"), str)
            ):
                raise ValueError(
                    "staged state JSON requires a registered top-level schema"
                )
            for record in _objects(value):
                schema_id = record.get("schema")
                if schema_id is None:
                    continue
                if not isinstance(schema_id, str) or schema_id not in self.validators:
                    raise ValueError(
                        f"staged JSON uses an unregistered schema: {schema_id!r}"
                    )
                try:
                    if schema_id not in self._schema_checked:
                        self._validator_classes[schema_id].check_schema(
                            self._documents[schema_id]
                        )
                        self._schema_checked.add(schema_id)
                    self.validators[schema_id].validate(record)
                except jsonschema.SchemaError as exc:
                    raise ValueError(
                        f"registered schema is invalid: {schema_id}: {exc.message}"
                    ) from exc
                except jsonschema.ValidationError as exc:
                    location = ".".join(str(item) for item in exc.absolute_path)
                    suffix = f" at {location}" if location else ""
                    raise ValueError(
                        f"staged {schema_id} schema validation failed{suffix}: "
                        f"{exc.message}"
                    ) from exc


__all__ = ["RegisteredSchemaValidator"]
