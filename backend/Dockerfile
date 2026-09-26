FROM python:3.12-slim
WORKDIR /srv
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .
CMD ["python", "-c", "import app; print(app.__version__)"]
