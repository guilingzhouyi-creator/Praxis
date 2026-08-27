FROM python:3.11-slim AS base

WORKDIR /praxis

# Install build deps + project
COPY pyproject.toml .
COPY .praxis-rules.md .
COPY systems/python-reference-runtime/ systems/python-reference-runtime/
COPY config/ config/
RUN pip install --no-cache-dir ".[test]"

FROM base AS kernel
CMD ["praxis-kernel"]

FROM base AS api
EXPOSE 8080
CMD ["praxis-api"]

FROM base AS sandbox
CMD ["praxis-sandbox"]

FROM base AS llm
CMD ["praxis-llm"]

FROM base AS supervisor
CMD ["praxis-supervisor"]
