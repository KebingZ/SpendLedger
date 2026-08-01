FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system spendledger && adduser --system --ingroup spendledger spendledger

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts

RUN pip install --no-cache-dir .

USER spendledger

EXPOSE 8000

CMD ["uvicorn", "spendledger.main:app", "--host", "0.0.0.0", "--port", "8000"]

