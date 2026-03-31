"""Context management — three-file system for each scope."""

from work.context.scopes import ScopeManager
from work.context.store import ContextStore

__all__ = ["ContextStore", "ScopeManager"]
