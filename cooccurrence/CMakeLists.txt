cmake_minimum_required(VERSION 3.16)

# ------------------------------------
# On macOS, force Homebrew LLVM clang
# ------------------------------------
if(APPLE)
    # Expect these env vars to be set:
    #   export BREW_LLVM_PREFIX=$(brew --prefix llvm)
    #   export BREW_LIBOMP_PREFIX=$(brew --prefix libomp)

    if(NOT DEFINED ENV{BREW_LLVM_PREFIX})
        message(FATAL_ERROR "BREW_LLVM_PREFIX is not set. Run: export BREW_LLVM_PREFIX=\$(brew --prefix llvm)")
    endif()
    if(NOT DEFINED ENV{BREW_LIBOMP_PREFIX})
        message(FATAL_ERROR "BREW_LIBOMP_PREFIX is not set. Run: export BREW_LIBOMP_PREFIX=\$(brew --prefix libomp)")
    endif()

    # Set compilers BEFORE project()
    set(CMAKE_C_COMPILER  "$ENV{BREW_LLVM_PREFIX}/bin/clang"    CACHE STRING "C compiler"  FORCE)
    set(CMAKE_CXX_COMPILER "$ENV{BREW_LLVM_PREFIX}/bin/clang++" CACHE STRING "C++ compiler" FORCE)
endif()

project(RepoReader LANGUAGES CXX)

# Use C++17
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# (Optional) put all executables directly in the build/ dir
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}")

# Header-only nlohmann/json (adjust if your path is different)
set(JSON_INCLUDE_DIR "${CMAKE_SOURCE_DIR}/json/include")

# -----------------
# Executables
# -----------------
add_executable(repo_reader      repo_reader.cpp)
add_executable(index2bipartite  index2bipartite.cpp)
add_executable(cooccur          cooccur.cpp)

# index2bipartite needs the json include directory
target_include_directories(index2bipartite PRIVATE "${JSON_INCLUDE_DIR}")
# If cooccur also needs JSON, uncomment this:
# target_include_directories(cooccur PRIVATE "${JSON_INCLUDE_DIR}")

# -----------------------------
# macOS: manual OpenMP wiring
# -----------------------------
if(APPLE)
    # Compile with OpenMP + O3
    target_compile_options(repo_reader      PRIVATE -O3 -fopenmp)
    target_compile_options(index2bipartite  PRIVATE -O3 -fopenmp)
    target_compile_options(cooccur          PRIVATE -O3 -fopenmp)

    # libomp include + lib dirs from Homebrew
    target_include_directories(repo_reader      PRIVATE "$ENV{BREW_LIBOMP_PREFIX}/include")
    target_include_directories(index2bipartite  PRIVATE "$ENV{BREW_LIBOMP_PREFIX}/include")
    target_include_directories(cooccur          PRIVATE "$ENV{BREW_LIBOMP_PREFIX}/include")

    target_link_directories(repo_reader      PRIVATE "$ENV{BREW_LIBOMP_PREFIX}/lib")
    target_link_directories(index2bipartite  PRIVATE "$ENV{BREW_LIBOMP_PREFIX}/lib")
    target_link_directories(cooccur          PRIVATE "$ENV{BREW_LIBOMP_PREFIX}/lib")

    # Link against libomp
    target_link_libraries(repo_reader      PRIVATE omp)
    target_link_libraries(index2bipartite  PRIVATE omp)
    target_link_libraries(cooccur          PRIVATE omp)

# -----------------------------
# Other platforms: use CMake's OpenMP
# -----------------------------
else()
    find_package(OpenMP REQUIRED)
    if(OpenMP_CXX_FOUND)
        target_compile_options(repo_reader      PRIVATE -O3 ${OpenMP_CXX_FLAGS})
        target_compile_options(index2bipartite  PRIVATE -O3 ${OpenMP_CXX_FLAGS})
        target_compile_options(cooccur          PRIVATE -O3 ${OpenMP_CXX_FLAGS})

        target_link_libraries(repo_reader      PRIVATE OpenMP::OpenMP_CXX)
        target_link_libraries(index2bipartite  PRIVATE OpenMP::OpenMP_CXX)
        target_link_libraries(cooccur          PRIVATE OpenMP::OpenMP_CXX)
    else()
        message(FATAL_ERROR "OpenMP not found")
    endif()
endif()