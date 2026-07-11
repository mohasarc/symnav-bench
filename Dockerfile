FROM docker:27-dind@sha256:aa3df78ecf320f5fafdce71c659f1629e96e9de0968305fe1de670e0ca9176ce

ARG SYMNAV_BENCH_VERSION=0.1.0

ENV SYMNAV_BENCH_VERSION=${SYMNAV_BENCH_VERSION}
ENV DEEPSWE_ROOT=/work/deep-swe

RUN apk upgrade --no-cache \
  && apk add --no-cache bash git python3 py3-pip nodejs npm pnpm

WORKDIR /opt/symnav-bench
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python3 -m pip install --break-system-packages --upgrade pip \
  && python3 -m pip install --break-system-packages --no-cache-dir .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
