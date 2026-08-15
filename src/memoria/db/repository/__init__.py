"""Memoria persistence layer (split package, compatible facade).

Historical code imported ``from memoria.db import repository`` and used
``repository.<symbol>``. This package preserves that surface by re-exporting
all domain symbols and injecting cross-module names into each submodule so
existing bare-name calls continue to work at runtime.

Monkeypatching ``repository.<symbol>`` also propagates into every domain
submodule, matching monolith behavior where tests patch the package surface.
"""

from __future__ import annotations

import sys
import types

from memoria.db.repository import (
    _common,
    background_jobs,
    characters,
    domain_events,
    events,
    fact_claims,
    knowledge,
    memory_curve,
    multi_session,
    relationships,
    sessions_and_messages,
    state_and_memory,
    story,
    users,
    world_clock,
)

_MODULES = (
    _common,
    background_jobs,
    domain_events,
    story,
    fact_claims,
    memory_curve,
    world_clock,
    state_and_memory,
    sessions_and_messages,
    characters,
    events,
    relationships,
    multi_session,
    knowledge,
    users,
)

_SKIP = {
    "__name__",
    "__doc__",
    "__package__",
    "__loader__",
    "__spec__",
    "__file__",
    "__cached__",
    "__builtins__",
    "__all__",
    "__path__",
    "__annotations__",
}

# Collect exported symbols (last writer wins, mirrors monolith order).
_EXPORTS: dict = {}
for _mod in _MODULES:
    for _name, _value in vars(_mod).items():
        if _name in _SKIP:
            continue
        _EXPORTS[_name] = _value

# Inject full symbol table into every submodule so cross-domain bare names resolve.
for _mod in _MODULES:
    for _name, _value in _EXPORTS.items():
        if _name not in _mod.__dict__:
            setattr(_mod, _name, _value)

globals().update(_EXPORTS)

# Keep module list for monkeypatch propagation (do not delete).
_SYNC_MODULES = _MODULES
_SYNC_SKIP = _SKIP | {
    "_MODULES",
    "_SYNC_MODULES",
    "_SYNC_SKIP",
    "_EXPORTS",
    "_SKIP",
    "_RepositoryPackage",
}


class _RepositoryPackage(types.ModuleType):
    """Propagate attribute writes/deletes to domain submodules."""

    def __setattr__(self, name: str, value) -> None:  # type: ignore[no-untyped-def]
        super().__setattr__(name, value)
        skip = self.__dict__.get("_SYNC_SKIP")
        modules = self.__dict__.get("_SYNC_MODULES")
        if not modules or (skip and name in skip):
            return
        for mod in modules:
            mod.__dict__[name] = value
        exports = self.__dict__.get("_EXPORTS")
        if isinstance(exports, dict):
            exports[name] = value

    def __delattr__(self, name: str) -> None:
        if name in self.__dict__:
            super().__delattr__(name)
        skip = self.__dict__.get("_SYNC_SKIP")
        modules = self.__dict__.get("_SYNC_MODULES")
        if not modules or (skip and name in skip):
            return
        for mod in modules:
            if name in mod.__dict__:
                del mod.__dict__[name]
        exports = self.__dict__.get("_EXPORTS")
        if isinstance(exports, dict):
            exports.pop(name, None)


sys.modules[__name__].__class__ = _RepositoryPackage

__all__ = [name for name in _EXPORTS if not name.startswith("__")]

# cleanup private loop vars
del _mod, _name, _value, _SKIP
