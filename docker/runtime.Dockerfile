FROM python:3.12-slim

WORKDIR /app

COPY runtime/pyproject.toml /app/runtime/pyproject.toml
COPY runtime/yozhan_runtime /app/runtime/yozhan_runtime
RUN pip install --no-cache-dir -e /app/runtime

COPY config /app/config

ENV YOZHAN_CONFIG_DIR=/app/config
EXPOSE 8787

ENTRYPOINT ["yozhan"]
CMD ["serve"]
