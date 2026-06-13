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
COPY src/ ./src/

# Configure and build the cloud task binary
RUN cmake --preset cloud
RUN cmake --build --preset cloud --target cloud_task -j

# Stage 2: Runtime stage
FROM debian:trixie-slim AS runtime

# Install the runtime libraries required by the OpenMP-enabled binary.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# Copy the binary from the build stage
COPY --from=build /build-cloud/cloud_task.x /cloud_task.x

ENTRYPOINT ["/cloud_task.x"]
