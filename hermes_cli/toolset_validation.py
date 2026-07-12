"""Validation for the ``platform_toolsets`` config section.

Pure, side-effect-free helpers so the logic is unit-testable without importing
the tool registry or launching Hermes (mirrors the decoupled-helper pattern used
elsewhere in the CLI).

Motivated by #38798: a config migration silently rewrote the valid toolset name
``hermes-cli`` to the non-existent ``hermes``. ``resolve_toolset('hermes')``
returns an empty list, so every tool silently disappeared with no error, warning,
or log entry — the agent degraded to text-only replies and the cause took
significant debugging to find. Surfacing invalid toolset names (and the
zero-tools end state) loudly turns that silent failure into an actionable one.
"""

from typing import Callable, Iterable, List, Mapping


DEFAULT_RUNTIME_TOOLSETS = ("hermes-cli",)


def _normalize_toolset_list(
    value: object,
    field: str,
    *,
    coerce_non_strings: bool = False,
) -> tuple[str, ...] | None:
    """Normalize one configured toolset list without importing tool modules."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a YAML list or null")

    normalized: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, str):
            if not coerce_non_strings:
                raise ValueError(f"{field}[{index}] must be a string")
            item = str(item)
        name = item.strip()
        if not name:
            raise ValueError(f"{field}[{index}] must not be empty")
        if name not in seen:
            normalized.append(name)
            seen.add(name)
    return tuple(normalized)


def normalize_runtime_toolsets(
    config: Mapping[str, object],
    platform: str,
    is_valid_toolset: Callable[[str], bool],
    *,
    external_toolsets: Iterable[str] = (),
) -> tuple[str, ...] | None:
    """Return the configured runtime selection for ``platform``.

    ``toolsets`` is the canonical global runtime selection. An explicit
    ``platform_toolsets.<platform>`` remains a supported platform override.
    The default-valued global selection is treated as a baseline so existing
    per-platform configurations remain compatible; a non-default global
    selection that disagrees with an explicit platform override is rejected.

    ``None`` means neither field selected a value and the caller should apply
    its established platform default. An explicit empty list remains an empty
    tuple. Unknown canonical entries are errors instead of silently becoming an
    empty runtime toolset.
    """
    global_names = _normalize_toolset_list(config.get("toolsets"), "toolsets")

    raw_platforms = config.get("platform_toolsets")
    if raw_platforms is not None and not isinstance(raw_platforms, Mapping):
        raise ValueError("platform_toolsets must be a mapping or null")
    platform_names = None
    if isinstance(raw_platforms, Mapping) and platform in raw_platforms:
        platform_names = _normalize_toolset_list(
            raw_platforms.get(platform),
            f"platform_toolsets.{platform}",
            # Legacy platform config accepts numeric MCP server names because
            # YAML parses bare numeric mapping keys as integers (#6901).
            coerce_non_strings=True,
        )

    allowed_external = {str(name) for name in external_toolsets}
    if global_names is not None:
        unknown = [
            name for name in global_names
            if name != "no_mcp"
            and name not in allowed_external
            and not is_valid_toolset(name)
        ]
        if unknown:
            raise ValueError(
                "toolsets references unknown toolset(s): " + ", ".join(unknown)
            )

    if (
        global_names is not None
        and global_names != DEFAULT_RUNTIME_TOOLSETS
        and platform_names is not None
        and global_names != platform_names
    ):
        raise ValueError(
            f"toolsets conflicts with platform_toolsets.{platform}; "
            "configure this runtime selection in only one place"
        )

    if platform_names is not None:
        return platform_names
    return global_names


def validate_platform_toolsets(
    platform_toolsets: object,
    is_valid_toolset: Callable[[str], bool],
) -> List[str]:
    """Return human-readable warnings for a ``platform_toolsets`` mapping.

    Two failure modes are reported:

    1. A toolset name that ``is_valid_toolset`` rejects — usually a corrupted or
       renamed entry. When ``hermes-<platform>`` would have been valid (the exact
       #38798 shape, where ``cli`` held ``hermes`` instead of ``hermes-cli``),
       the warning includes that as a suggestion.
    2. The mapping is non-empty but resolves to *zero* valid toolsets, so the
       agent would start with no tools at all.

    ``is_valid_toolset`` is injected (normally :func:`toolsets.validate_toolset`)
    so this function performs no imports or I/O and is testable in isolation.

    Args:
        platform_toolsets: The raw ``platform_toolsets`` value from config. Only
            ``dict`` values carry toolset entries; anything else yields no
            warnings (nothing to validate).
        is_valid_toolset: Predicate returning ``True`` for a known toolset name.

    Returns:
        A list of warning strings (empty when everything is valid).
    """
    warnings: List[str] = []
    if not isinstance(platform_toolsets, dict) or not platform_toolsets:
        return warnings

    valid_count = 0
    for platform, raw in platform_toolsets.items():
        names = raw if isinstance(raw, list) else [raw]
        for name in names:
            if not isinstance(name, str) or not name:
                continue
            if is_valid_toolset(name):
                valid_count += 1
                continue
            suggestion = f"hermes-{platform}"
            hint = (
                f" — did you mean '{suggestion}'?"
                if is_valid_toolset(suggestion)
                else ""
            )
            warnings.append(
                f"platform '{platform}' references unknown toolset "
                f"'{name}'{hint}"
            )

    if valid_count == 0:
        warnings.append(
            "platform_toolsets resolves to zero valid toolsets — the agent will "
            "have no tools. Run `hermes tools` to reconfigure."
        )
    return warnings
