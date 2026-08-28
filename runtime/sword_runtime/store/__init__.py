"""Filesystem-backed campaign owner access."""

from importlib import import_module

__all__ = [
    "ContentRoot",
    "CommittedContentRootCache",
    "RepositoryStore",
    "RegisteredSchemaValidator",
    "RegisteredTemplateValidator",
    "RootEntry",
    "StagedOverlay",
    "atomic_replace_bytes",
    "content_root",
]


_EXPORT_MODULES = {
    "RepositoryStore": ".repository",
    "RegisteredSchemaValidator": ".schema_validation",
    "RegisteredTemplateValidator": ".template_validation",
    "StagedOverlay": ".overlay",
    "atomic_replace_bytes": ".repository",
    "ContentRoot": ".root_hash",
    "CommittedContentRootCache": ".root_hash",
    "RootEntry": ".root_hash",
    "content_root": ".root_hash",
}


def __getattr__(name: str):
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
