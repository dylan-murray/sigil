from pydantic import BaseModel, ConfigDict, Field, field_validator

_FORBIDDEN_FILE_CHARS = frozenset("\n\r\t<>\x00")


def _validate_file_path(v: str) -> str:
    if not v:
        raise ValueError("value must not be empty")
    if any(c in _FORBIDDEN_FILE_CHARS for c in v):
        raise ValueError("value contains invalid characters (newlines, tabs, or angle brackets)")
    return v


class ApplyEditArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str = Field(
        description=(
            "Path to the file to edit, relative to the repo root. Plain string only — "
            "do NOT embed other tool parameters or markup."
        )
    )
    old_content: str = Field(
        description=(
            "Exact content to find in the file. Must match precisely, including "
            "whitespace and indentation."
        )
    )
    new_content: str = Field(description="Content to replace old_content with.")

    _validate_file = field_validator("file")(_validate_file_path)


class EditSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_content: str = Field(description="Exact content to find.")
    new_content: str = Field(description="Content to replace with.")


class MultiEditArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str = Field(description="Path to the file to edit, relative to the repo root.")
    edits: list[EditSpec] = Field(
        min_length=1,
        description="List of edits to apply sequentially.",
    )

    _validate_file = field_validator("file")(_validate_file_path)


class CreateFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str = Field(description="Path to the file to create, relative to the repo root.")
    content: str = Field(description="Full content for the new file.")

    _validate_file = field_validator("file")(_validate_file_path)


_DEFAULT_READ_LIMIT = 2000


class ReadFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str = Field(
        description=(
            "File path relative to the repo root. Plain string only — "
            "do NOT embed other tool parameters or markup."
        )
    )
    offset: int = Field(
        default=1,
        ge=1,
        description="Line number to start reading from (1-based, default 1).",
    )
    limit: int = Field(
        default=_DEFAULT_READ_LIMIT,
        ge=1,
        description="Maximum number of lines to return (default 2000).",
    )

    _validate_file = field_validator("file")(_validate_file_path)


class GrepArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(description="Regex pattern to search for.")
    path: str = Field(
        default=".",
        description="Directory or file to search in, relative to repo root. Defaults to repo root.",
    )
    include: str = Field(
        default="",
        description="Glob pattern to filter files (e.g. '*.py', '*.ts').",
    )

    _validate_path = field_validator("path")(_validate_file_path)


class ListDirectoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        default=".",
        description="Directory path relative to repo root. Use '.' for root.",
    )
    depth: int = Field(
        default=1,
        description=(
            "Max depth to recurse. 1 = immediate children only (default). "
            "2 = one level of subdirs. Max 3."
        ),
    )

    _validate_path = field_validator("path")(_validate_file_path)
