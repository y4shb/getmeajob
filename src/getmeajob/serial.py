"""JSON (de)serialisation for the dataclasses in `getmeajob.models`.

`Model` gives a dataclass `to_dict()` (JSON-safe, enums as values) and `from_dict()`
(ignores unknown keys, fills defaults, coerces enums, nested models and lists).
"""

from __future__ import annotations

import dataclasses
import types
from collections.abc import Callable, Mapping
from enum import Enum
from pathlib import Path
from typing import Any, Self, Union, cast, get_args, get_origin, get_type_hints

from getmeajob.errors import StoreError

_HINTS: dict[type, dict[str, Any]] = {}
_MISSING = object()


def _hints(cls: type) -> dict[str, Any]:
    hints = _HINTS.get(cls)
    if hints is None:
        hints = get_type_hints(cls)
        _HINTS[cls] = hints
    return hints


def _is_union(tp: Any) -> bool:
    return get_origin(tp) in (Union, types.UnionType)


def _allows_none(tp: Any) -> bool:
    return tp is Any or (_is_union(tp) and type(None) in get_args(tp))


def _empty_for(tp: Any) -> Any:
    """Neutral value for a required field that is missing, or `_MISSING` when none fits."""
    if _allows_none(tp):
        return None
    origin = get_origin(tp)
    if origin is list:
        return []
    if origin is dict:
        return {}
    if origin is set:
        return set()
    return _MISSING


def _fits(tp: Any, value: Any) -> bool:
    origin = get_origin(tp)
    if origin is not None:
        return isinstance(value, origin) or (origin is list and isinstance(value, tuple))
    if isinstance(tp, type):
        if issubclass(tp, Enum):
            return isinstance(value, tp) or value in {m.value for m in tp}
        if dataclasses.is_dataclass(tp):
            return isinstance(value, (tp, Mapping))
        return isinstance(value, tp)
    return False


def _coerce(tp: Any, value: Any) -> Any:
    """Turn a JSON value into the annotated type (enums, nested models, lists)."""
    if value is None or tp is Any:
        return value
    if _is_union(tp):
        options = [a for a in get_args(tp) if a is not type(None)]
        for option in options:
            if _fits(option, value):
                return _coerce(option, value)
        return _coerce(options[0], value) if options else value
    origin = get_origin(tp)
    args = get_args(tp)
    if origin is list:
        item = args[0] if args else Any
        items = value if isinstance(value, list | tuple) else [value]
        return [_coerce(item, v) for v in items]
    if origin is set:
        item = args[0] if args else Any
        members = value if isinstance(value, list | tuple | set | frozenset) else [value]
        return {_coerce(item, v) for v in members}
    if origin is dict:
        val_tp = args[1] if len(args) == 2 else Any
        return {str(k): _coerce(val_tp, v) for k, v in dict(value).items()}
    if isinstance(tp, type):
        if issubclass(tp, Enum):
            return value if isinstance(value, tp) else tp(value)
        if dataclasses.is_dataclass(tp) and isinstance(value, Mapping):
            return cast(Any, tp).from_dict(value)
        if tp is str and isinstance(value, int | float) and not isinstance(value, bool):
            return str(value)
        if tp is float and isinstance(value, int) and not isinstance(value, bool):
            return float(value)
    return value


def to_jsonable(value: Any) -> Any:
    """Convert models, enums, paths, sets and tuples into plain JSON values."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Model):
        return value.to_dict()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, set | frozenset):
        return sorted((to_jsonable(v) for v in value), key=str)
    if isinstance(value, list | tuple):
        return [to_jsonable(v) for v in value]
    return value


class Model:
    """Mixin that gives a dataclass `to_dict` and `from_dict`."""

    __slots__ = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            f.name: to_jsonable(getattr(self, f.name)) for f in dataclasses.fields(cast(Any, self))
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        if not isinstance(d, Mapping):
            raise StoreError(
                f"Expected a {cls.__name__} record (a JSON object), got {type(d).__name__}.",
                hint="The data file may be damaged. Re-run the command that writes it.",
            )
        hints = _hints(cls)
        kwargs: dict[str, Any] = {}
        missing: list[str] = []
        for f in dataclasses.fields(cast(Any, cls)):
            tp = hints[f.name]
            raw = d.get(f.name)
            has_default = (
                f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING
            )
            if raw is None and not _allows_none(tp):
                # Missing, or null where a value is required: use the default if there is one.
                if has_default:
                    continue
                empty = _empty_for(tp)
                if empty is _MISSING:
                    missing.append(f.name)
                else:
                    kwargs[f.name] = empty
                continue
            if f.name not in d and has_default:
                continue
            try:
                kwargs[f.name] = _coerce(tp, raw)
            except (TypeError, ValueError) as exc:
                raise StoreError(
                    f"{cls.__name__} record has a bad value for '{f.name}': {exc}",
                    hint="The data file may be damaged or edited by hand. Fix that value.",
                ) from exc
        if missing:
            raise StoreError(
                f"{cls.__name__} record is missing: {', '.join(missing)}.",
                hint="The data file may be from another version or edited by hand.",
            )
        factory: Callable[..., Self] = cls
        return factory(**kwargs)
