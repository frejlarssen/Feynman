# Stage 1: Build stage
FROM ubuntu:24.04 AS build

# Install build-essential for compiling C++ code
RUN apt-get update && apt-get install -y build-essential cmake ninja-build pkg-config

# Set the working directory
WORKDIR /

# Copy the build and source code into the container
COPY CMakePresets.json ./
COPY CMakeLists.txt ./
COPY apps/cloud_task.cpp ./apps/
COPY src/ ./src/

# Compile the C++ code statically to ensure it doesn't depend on runtime libraries
RUN cmake --preset cloud
RUN cmake --build --preset cloud --target cloud_task -j

# Stage 2: Runtime stage
FROM scratch AS runtime

# Copy the static binary from the build stage
COPY --from=build /build-cloud/cloud_task.x /cloud_task.x

# Command to run the binary
CMD ["/cloud_task.x \
  -c data/generated/circuits/qft/qft_n8_k2.qasm \
  -i data/generated/statevectors/ket0_size1.hsv \
  -b data/generated/hexstring_sets/nrhex10_size1_from0x0_to0xA.hs \
  -o data/outputs/tmp/qft_n8_k2_run_cloud.hsv \
  -t 0.0 -v 1"]
