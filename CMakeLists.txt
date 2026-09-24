cmake_minimum_required(VERSION 3.16)
project(Feynman LANGUAGES CXX)

option(BUILD_MPI_TARGETS "Build the MPI simulator" ON)
option(FEYNMAN_ENABLE_LINUX_PERF "Enable Linux perf_event instrumentation for simulators" OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()
if(FEYNMAN_ENABLE_LINUX_PERF AND NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
  message(FATAL_ERROR "FEYNMAN_ENABLE_LINUX_PERF requires Linux perf_event support.")
endif()

add_library(feynman_settings INTERFACE)
target_compile_features(feynman_settings INTERFACE cxx_std_17)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(OpenMP REQUIRED COMPONENTS CXX)
add_library(feynman_simulator INTERFACE)
target_link_libraries(feynman_simulator INTERFACE feynman_settings OpenMP::OpenMP_CXX)
target_compile_definitions(feynman_simulator INTERFACE USE_OPENMP
  FEYNMAN_ENABLE_LINUX_PERF=$<BOOL:${FEYNMAN_ENABLE_LINUX_PERF}>)

function(feynman_executable name)
  add_executable(${name} apps/${name}.cpp)
  target_link_libraries(${name} PRIVATE feynman_settings)
  set_target_properties(${name} PROPERTIES OUTPUT_NAME ${name}.x)
endfunction()

feynman_executable(feynman)
target_link_libraries(feynman PRIVATE feynman_simulator)

if(BUILD_MPI_TARGETS)
  find_package(MPI REQUIRED COMPONENTS CXX)
  feynman_executable(feynman_mpi)
  target_compile_definitions(feynman_mpi PRIVATE USE_MPI)
  target_link_libraries(feynman_mpi PRIVATE feynman_simulator MPI::MPI_CXX)
endif()

feynman_executable(feynman_split_batches)
feynman_executable(feynman_concat_batches)
