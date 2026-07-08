FROM docker:27-dind

ARG DEEPSWE_REF=main
ARG SYMNAV_BENCH_VERSION=0.1.0

ENV DEEPSWE_TASKS_DIR=/opt/deep-swe/tasks
ENV SYMNAV_BENCH_VERSION=${SYMNAV_BENCH_VERSION}

RUN apk add --no-cache bash git python3 py3-pip nodejs npm pnpm

RUN git clone https://github.com/datacurve-ai/deep-swe.git /opt/deep-swe \
  && cd /opt/deep-swe \
  && git checkout "${DEEPSWE_REF}"

WORKDIR /opt/symnav-bench
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python3 -m venv /opt/venv \
  && /opt/venv/bin/pip install --upgrade pip \
  && /opt/venv/bin/pip install .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PATH=/opt/venv/bin:$PATH
ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
