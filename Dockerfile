# Stage 1: Build stage
FROM debian:trixie AS build

# Install build-essential for compiling C++ code
RUN apt-get update && apt-get install -y build-essential cmake pkg-config

# Set the working directory
WORKDIR /

# Copy the build and source code into the container
COPY CMakePresets.json ./
COPY CMakeLists.txt ./
COPY apps/feynman.cpp ./apps/
COPY apps/feynman_split_batches.cpp ./apps/
COPY apps/feynman_concat_batches.cpp ./apps/
COPY src/ ./src/

# Configure and build the cloud workflow binaries
RUN cmake --preset standalone
RUN cmake --build --preset standalone --target feynman feynman_split_batches feynman_concat_batches -j

# Stage 2: Shared runtime base
FROM debian:trixie-slim AS runtime-base

# Install the runtime libraries required by the OpenMP-enabled binary.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# Stage 3a: Simulation image
FROM runtime-base AS simulate
COPY --from=build /build-standalone/feynman.x /feynman.x
ENTRYPOINT ["/feynman.x"]

# Stage 3b: Batch splitting image
FROM runtime-base AS split
COPY --from=build /build-standalone/feynman_split_batches.x /feynman_split_batches.x
ENTRYPOINT ["/feynman_split_batches.x"]

# Stage 3c: Batch concatenation image
FROM runtime-base AS concat
COPY --from=build /build-standalone/feynman_concat_batches.x /feynman_concat_batches.x
ENTRYPOINT ["/feynman_concat_batches.x"]
