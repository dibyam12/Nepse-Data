"""
Database router for dual SQLite (local) + Neon PostgreSQL setup.

When both 'default' (SQLite) and 'neon' databases are configured,
this router keeps all reads/writes on 'default' unless explicitly
directed to 'neon' via .using('neon').

On production (Render), 'default' IS the Neon DB, so this router
is effectively a no-op.
"""


class NeonRouter:
    """Route DB operations — default stays local, 'neon' is explicit."""

    def db_for_read(self, model, **hints):
        return 'default'

    def db_for_write(self, model, **hints):
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return True
