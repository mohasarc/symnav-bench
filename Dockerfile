FROM docker:27-dind@sha256:aa3df78ecf320f5fafdce71c659f1629e96e9de0968305fe1de670e0ca9176ce

ARG SYMNAV_BENCH_VERSION=0.1.0
ARG SYMNAV_BENCH_SHA=unknown
ARG SYMNAV_BENCH_IMAGE_VERSION=local

ENV SYMNAV_BENCH_VERSION=${SYMNAV_BENCH_VERSION}
ENV SYMNAV_BENCH_SHA=${SYMNAV_BENCH_SHA}
ENV SYMNAV_BENCH_IMAGE_VERSION=${SYMNAV_BENCH_IMAGE_VERSION}
ENV DEEPSWE_ROOT=/work/deep-swe

RUN apk upgrade --no-cache \
  && apk add --no-cache bash git python3 py3-pip nodejs npm pnpm

WORKDIR /opt/symnav-bench
COPY pyproject.toml requirements.lock README.md LICENSE ./
COPY src ./src
RUN python3 -m pip install --break-system-packages --upgrade pip \
  && python3 -m pip install --break-system-packages --no-cache-dir -r requirements.lock \
  && python3 -m pip install --break-system-packages --no-cache-dir --no-deps .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
