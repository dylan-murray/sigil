# API Reference — Core Data Structures for Findings, Ideas, and Configuration

## `Finding` Dataclass

Represents a potential issue or improvement identified in the codebase.

```python
@dataclass(frozen=True)
class Finding:
    category: str
    file: str
    line: int | None
    description: str
    risk: str
    suggested_fix: str
    disposition: str
    priority: int
    rationale: str
    implementation_spec: str = ""
    relevant_files: tuple[str, ...] = ()
    boldness: str = "balanced"
```

## `FeatureIdea` Dataclass

Represents a proposed new feature or significant enhancement.

```python
@dataclass(frozen=True)
class FeatureIdea:
    title: str
    description: str
    summary: str
    complexity: str
    disposition: str
    priority: int
    implementation_spec: str = ""
    relevant_files: tuple[str, ...] = ()
    boldness: str = "balanced"
```

## `BOLDNESS_RANK` Constant

Defines the ranking of boldness levels for comparison.

```python
BOLDNESS_RANK: dict[str, int] = {
    "conservative": 0,
    "balanced": 1,
    "bold": 2,
    "experimental": 3,
}
```

## `boldness_allowed` Function

Determines if an item's boldness level is allowed given the current configuration's boldness.

```python
def boldness_allowed(item_boldness: str, current_boldness: str) -> bool:
    return BOLDNESS_RANK.get(item_boldness, 1) <= BOLDNESS_RANK.get(current_boldness, 1)
```
