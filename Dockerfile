# Stage 1: Build stage
FROM debian:trixie AS build

# Install build-essential for compiling C++ code
RUN apt-get update && apt-get install -y build-essential cmake ninja-build pkg-config

# Set the working directory
WORKDIR /

# Copy the build and source code into the container
COPY CMakePresets.json ./
COPY CMakeLists.txt ./
COPY apps/cloud_task.cpp ./apps/
COPY apps/cloud_split_batches.cpp ./apps/
COPY apps/cloud_concat_batches.cpp ./apps/
COPY src/ ./src/

# Configure and build the cloud workflow binaries
RUN cmake --preset cloud
RUN cmake --build --preset cloud --target cloud_task cloud_split_batches cloud_concat_batches -j

# Stage 2: Shared runtime base
FROM debian:trixie-slim AS runtime-base

# Install the runtime libraries required by the OpenMP-enabled binary.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# Stage 3a: Simulation image
FROM runtime-base AS simulate
COPY --from=build /build-cloud/cloud_task.x /cloud_task.x
ENTRYPOINT ["/cloud_task.x"]

# Stage 3b: Batch splitting image
FROM runtime-base AS split
COPY --from=build /build-cloud/cloud_split_batches.x /cloud_split_batches.x
ENTRYPOINT ["/cloud_split_batches.x"]

# Stage 3c: Batch concatenation image
FROM runtime-base AS concat
COPY --from=build /build-cloud/cloud_concat_batches.x /cloud_concat_batches.x
ENTRYPOINT ["/cloud_concat_batches.x"]
