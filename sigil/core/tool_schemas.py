from pydantic import BaseModel, ConfigDict, Field, field_validator

_FORBIDDEN_FILE_CHARS = frozenset("\n\r\t<>\x00")


def _validate_file_path(v: str) -> str:
    if not v:
        raise ValueError("file must not be empty")
    if any(c in _FORBIDDEN_FILE_CHARS for c in v):
        raise ValueError("file contains invalid characters (newlines, tabs, or angle brackets)")
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
