"""Safe repository-relative path handling."""

from pathlib import PurePosixPath


def normalize_relative_path(value: object) -> str:
    """Return a normalized POSIX path or reject ambiguous/escaping input."""

    if not isinstance(value, str) or not value:
        raise ValueError("repository path must be a non-empty string")
    if "\\" in value or any(ord(character) < 32 for character in value):
        raise ValueError("repository path contains an invalid character")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError("repository path must be relative")
    if value != path.as_posix():
        raise ValueError("repository path must already be normalized")
    if not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("repository path may not contain dot segments")
    if path.as_posix() == ".":
        raise ValueError("repository root is not a valid file path")
    return path.as_posix()
