FROM python:3.12-slim
LABEL authors="decurzion"

COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Dependencies come from the lockfile, in their own layer so code changes do not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Only the application code is copied; secrets reach the container through env_file, not the image.
COPY app ./app

RUN useradd --system --uid 10001 --no-create-home luma
USER luma

CMD ["python", "-m", "app.bot"]
