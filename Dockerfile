# Build stage: uv resolves and installs the dependencies into a virtualenv.
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv

WORKDIR /app
# Use the image's own Python so the virtualenv also works in the final stage, which has the same base image.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Copy only the dependency manifests before installing, so code changes reuse this cached layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project


# Final stage: only the virtualenv and the application code; no uv, no build cache.
FROM python:3.12-slim

# UID 1000 matches the usual first user on a Linux host, so files written to the bind-mounted ./data stay owned by that user.
RUN useradd --uid 1000 --create-home app

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"

COPY --from=builder /app/.venv ./.venv
# pyproject.toml holds the [tool.fastapi] entrypoint that `fastapi run` reads.
COPY --chown=app:app pyproject.toml ./
COPY --chown=app:app app ./app
COPY --chown=app:app frontend ./frontend
RUN mkdir data && chown app:app data

USER app
EXPOSE 8000
CMD ["fastapi", "run", "--port", "8000"]
