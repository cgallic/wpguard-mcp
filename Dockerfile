# syntax=docker/dockerfile:1

# --- build stage: install the package + deps into a venv ---
FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only what's needed to build the wheel, then install.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install .

# --- runtime stage: minimal image, non-root, venv only ---
FROM python:3.12-slim AS runtime

# openssh-client so the SSH+WP-CLI transport works out of the box.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Non-root user; state dir it owns.
RUN useradd --create-home --uid 10001 wpguard \
    && mkdir -p /state \
    && chown wpguard:wpguard /state

COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    WPGUARD_MCP_HOST=0.0.0.0 \
    WPGUARD_MCP_PORT=8642 \
    WPGUARD_STATE_DIR=/state

USER wpguard
WORKDIR /home/wpguard

# The packet ledger, snapshots, and site registry live here; mount a volume so
# they survive container restarts.
VOLUME ["/state"]
EXPOSE 8642

# WPGUARD_MCP_TOKEN (or a scoped token) MUST be provided at run time; the
# server fails closed without one.
ENTRYPOINT ["wpguard-mcp"]
