cmake_minimum_required(VERSION 3.16)

project(Feynman LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(BUILD_MPI_TARGETS "Build MPI executables" ON)
option(FEYNMAN_ENABLE_LINUX_PERF "Enable Linux perf_event instrumentation for sv_prefetcher targets" OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

if(BUILD_MPI_TARGETS)
  find_package(MPI REQUIRED)
endif()
  
if(FEYNMAN_ENABLE_LINUX_PERF AND NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
  message(FATAL_ERROR "FEYNMAN_ENABLE_LINUX_PERF requires Linux perf_event support.")
endif()
find_package(OpenMP REQUIRED)

function(add_feynman_target_nompi target_name source_file)
  add_executable(${target_name} ${source_file})
  target_compile_options(${target_name} PRIVATE)
endfunction()

function(add_feynman_target target_name source_file)
  add_executable(${target_name} ${source_file})
  target_compile_options(${target_name} PRIVATE)
  target_compile_definitions(bitstr_omp PRIVATE USE_MPI)
  target_link_libraries(${target_name} PRIVATE MPI::MPI_CXX)
endfunction()

function(enable_linux_perf target_name)
  if(FEYNMAN_ENABLE_LINUX_PERF)
    target_compile_definitions(${target_name} PRIVATE FEYNMAN_ENABLE_LINUX_PERF=1)
  endif()
endfunction()

if(BUILD_MPI_TARGETS)
  add_feynman_target(bitstr_omp apps/bitstr.cpp)
  target_compile_definitions(bitstr_omp PRIVATE USE_OPENMP)
  target_link_libraries(bitstr_omp PRIVATE OpenMP::OpenMP_CXX)
  set_target_properties(bitstr_omp PROPERTIES OUTPUT_NAME bitstr.x)
  
  add_feynman_target(bitstr_mpi apps/bitstr.cpp)
  target_compile_definitions(bitstr_mpi PRIVATE USE_MPI)
  set_target_properties(bitstr_mpi PROPERTIES OUTPUT_NAME bitstr_mpi.x)
  
  add_feynman_target(sv_batch_mpi apps/sv_batch.cpp)
  target_compile_definitions(sv_batch_mpi PRIVATE USE_OPENMP)
  target_link_libraries(sv_batch_mpi PRIVATE OpenMP::OpenMP_CXX)
  set_target_properties(sv_batch_mpi PROPERTIES OUTPUT_NAME sv_batch_mpi.x)
  
  add_feynman_target(sv_scheduler_mpi apps/sv_scheduler.cpp)
  target_compile_definitions(sv_scheduler_mpi PRIVATE USE_OPENMP)
  target_link_libraries(sv_scheduler_mpi PRIVATE OpenMP::OpenMP_CXX)
  set_target_properties(sv_scheduler_mpi PROPERTIES OUTPUT_NAME sv_scheduler_mpi.x)
  
  add_feynman_target(sv_prefetcher_mpi apps/sv_prefetcher.cpp)
  target_compile_definitions(sv_prefetcher_mpi PRIVATE USE_OPENMP)
  enable_linux_perf(sv_prefetcher_mpi)
  target_link_libraries(sv_prefetcher_mpi PRIVATE OpenMP::OpenMP_CXX)
  set_target_properties(sv_prefetcher_mpi PROPERTIES OUTPUT_NAME sv_prefetcher_mpi.x)
endif()

add_feynman_target_nompi(cloud_task apps/cloud_task.cpp)
target_compile_definitions(
  cloud_task PRIVATE USE_OPENMP
)
target_link_libraries(cloud_task PRIVATE OpenMP::OpenMP_CXX)

set_target_properties(
  cloud_task PROPERTIES OUTPUT_NAME cloud_task.x
)

add_feynman_target_nompi(cloud_split_batches apps/cloud_split_batches.cpp)
set_target_properties(
  cloud_split_batches PROPERTIES OUTPUT_NAME cloud_split_batches.x
)

add_feynman_target_nompi(cloud_concat_batches apps/cloud_concat_batches.cpp)
set_target_properties(
  cloud_concat_batches PROPERTIES OUTPUT_NAME cloud_concat_batches.x
)

if(BUILD_MPI_TARGETS)
  add_feynman_target(sv_prefetcher_mpi_subsetbitstrings apps/sv_prefetcher.cpp)
  target_compile_definitions(
    sv_prefetcher_mpi_subsetbitstrings PRIVATE USE_OPENMP USE_SUBSET_OUTBITSTRINGS
  )
  enable_linux_perf(sv_prefetcher_mpi_subsetbitstrings)
  target_link_libraries(sv_prefetcher_mpi_subsetbitstrings PRIVATE OpenMP::OpenMP_CXX)
  set_target_properties(
    sv_prefetcher_mpi_subsetbitstrings PROPERTIES OUTPUT_NAME sv_prefetcher_subset_mpi.x
  )
  
  add_feynman_target(sv_prefetcher_mpi_subsetbitstrings_noomp apps/sv_prefetcher.cpp)
  target_compile_definitions(
    sv_prefetcher_mpi_subsetbitstrings_noomp PRIVATE USE_SUBSET_OUTBITSTRINGS
  )
  enable_linux_perf(sv_prefetcher_mpi_subsetbitstrings_noomp)
  set_target_properties(
    sv_prefetcher_mpi_subsetbitstrings_noomp
    PROPERTIES OUTPUT_NAME sv_prefetcher_subset_noomp_mpi.x
  )
endif()
