FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# templates/ (OPT files) and /vault are mounted by docker-compose
ENTRYPOINT []
CMD ["hci", "watch"]
