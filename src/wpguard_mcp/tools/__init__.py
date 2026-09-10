"""wpguard-mcp tool modules."""
from . import (
    blocks,
    cli_jobs,
    eval_sandbox,
    files,
    magic_login,
    mutate,
    packets,
    pages,
    recon,
    rollback,
    schema_recon,
    skills,
)

__all__ = [
    "blocks",
    "cli_jobs",
    "eval_sandbox",
    "files",
    "magic_login",
    "mutate",
    "packets",
    "pages",
    "recon",
    "rollback",
    "schema_recon",
    "skills",
]

# One importable registry for every operation that can write only after the
# shared packet gate. Individual modules retain their local registries so their
# focused tests can patch the gate at the module boundary.
GUARDED_TOOLS = {**mutate.GUARDED_TOOLS, **pages.GUARDED_TOOLS}
