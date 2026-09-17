FROM python:3.14-slim AS build

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    patchelf \
    tk \
    && rm -rf /var/lib/apt/lists/*

# official uv distribution image (pin with a version tag, e.g. uv:0.8.0)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN uv pip install --system --no-cache-dir nuitka

ARG APP_ENTRY=hello.py
ARG BIN_NAME=hello
ARG NUITKA_EXTRA_ARGS=""
ARG PKG_NAME=hello
ARG PKG_VERSION=1.0.0
ARG PKG_ARCH=amd64
ARG PKG_MAINTAINER="app <app@example.com>"
ARG PKG_DESCRIPTION="Hello application"

WORKDIR /home/app/product

COPY ./product/requirements.txt* ./product/pyproject.toml* ./product/uv.lock* ./
RUN if [ -f requirements.txt ]; then \
        uv pip install --system --no-cache-dir -r requirements.txt; \
    fi \
    && if [ -f pyproject.toml ]; then \
        uv sync --frozen --no-dev; \
    fi

COPY ./product ./

RUN nuitka --standalone --onefile --output-dir=/home/app/dist \
    --output-filename="${BIN_NAME}.bin" ${NUITKA_EXTRA_ARGS} "${APP_ENTRY}"

RUN mkdir -p /home/app/deb/DEBIAN "/home/app/deb/opt/${PKG_NAME}" /home/app/deb/usr/bin \
    && cp "/home/app/dist/${BIN_NAME}.bin" "/home/app/deb/opt/${PKG_NAME}/${BIN_NAME}" \
    && chmod 755 "/home/app/deb/opt/${PKG_NAME}/${BIN_NAME}" \
    && ln -s "/opt/${PKG_NAME}/${BIN_NAME}" "/home/app/deb/usr/bin/${BIN_NAME}" \
    && printf 'Package: %s\nVersion: %s\nSection: utils\nPriority: optional\nArchitecture: %s\nMaintainer: %s\nDescription: %s\n' \
        "${PKG_NAME}" "${PKG_VERSION}" "${PKG_ARCH}" "${PKG_MAINTAINER}" "${PKG_DESCRIPTION}" \
        > /home/app/deb/DEBIAN/control \
    && dpkg-deb --build /home/app/deb "/home/app/dist/${PKG_NAME}_${PKG_VERSION}_${PKG_ARCH}.deb"

FROM scratch AS artifact
COPY --from=build /home/app/dist/*.deb /