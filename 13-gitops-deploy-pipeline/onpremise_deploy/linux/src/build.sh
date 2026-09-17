#!/bin/sh
# pass to docker build as build-arg from env file and output deb to ./out
# HOW TO USE: ./build.sh [env file's path]   (default: env/.env)
set -e
cd "$(dirname "$0")"

ENV_FILE="${1:-env/.env}"
if [ ! -f "$ENV_FILE" ]; then
    echo "NO ENV: $ENV_FILE" >&2
    echo "Please run this command: cp env/.env.example env/.env" >&2
    exit 1
fi

set -a
. "$ENV_FILE"
set +a

docker build \
    --build-arg APP_ENTRY \
    --build-arg BIN_NAME \
    --build-arg NUITKA_EXTRA_ARGS \
    --build-arg PKG_NAME \
    --build-arg PKG_VERSION \
    --build-arg PKG_ARCH \
    --build-arg PKG_MAINTAINER \
    --build-arg PKG_DESCRIPTION \
    --target artifact --output type=local,dest=./out .
