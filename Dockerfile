FROM docker:27-dind

ARG SYMNAV_BENCH_VERSION=0.1.0

ENV SYMNAV_BENCH_VERSION=${SYMNAV_BENCH_VERSION}
ENV DEEPSWE_ROOT=/work/deep-swe

RUN apk add --no-cache bash git python3 py3-pip nodejs npm pnpm

WORKDIR /opt/symnav-bench
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python3 -m pip install --break-system-packages --upgrade pip \
  && python3 -m pip install --break-system-packages --no-cache-dir .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
