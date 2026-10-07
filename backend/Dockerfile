FROM ghcr.io/astral-sh/uv:0.5 AS uv

FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /srv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# 可选：构建时注入 PyPI 镜像加速（--build-arg UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple）
ARG UV_DEFAULT_INDEX=""
ENV UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX:-https://pypi.org/simple}

# 依赖层缓存：先只装依赖，再拷源码装项目（改代码不重装依赖）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
RUN uv sync --frozen --no-dev

ENV PATH="/srv/.venv/bin:$PATH" \
    ENSEMBLE_SQLITE_PATH=/data/ensemble.db \
    ENSEMBLE_MODULES_DIR=/modules \
    ENSEMBLE_PRICING_PATH=/config/pricing.yaml

EXPOSE 8000
CMD ["uvicorn", "app.serve:app", "--host", "0.0.0.0", "--port", "8000"]
