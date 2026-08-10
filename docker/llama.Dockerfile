# Builds llama.cpp from source and runs llama-server with an OpenAI-compatible
# API. CPU build by default; pass --build-arg LLAMA_BUILD=cuda for a GPU build
# (see docker-compose.cuda.yml). We never reimplement llama.cpp, only build
# and invoke it.

ARG LLAMA_BUILD=cpu
FROM ubuntu:24.04 AS builder
ARG LLAMA_BUILD

RUN apt-get update && apt-get install -y --no-install-recommends \
        git cmake build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/ggml-org/llama.cpp /src/llama.cpp
WORKDIR /src/llama.cpp

RUN if [ "$LLAMA_BUILD" = "cuda" ]; then \
        cmake -B build -DGGML_CUDA=ON -DLLAMA_CURL=ON -DCMAKE_BUILD_TYPE=Release; \
    else \
        cmake -B build -DLLAMA_CURL=ON -DCMAKE_BUILD_TYPE=Release; \
    fi \
    && cmake --build build --target llama-server -j"$(nproc)"

FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates libcurl4 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /src/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server

ENV LLAMA_CACHE=/models
VOLUME ["/models"]
EXPOSE 8080

COPY docker/llama-entrypoint.sh /usr/local/bin/llama-entrypoint.sh
RUN chmod +x /usr/local/bin/llama-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/llama-entrypoint.sh"]
