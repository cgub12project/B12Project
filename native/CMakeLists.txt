cmake_minimum_required(VERSION 3.22.1)
project(flash_inference LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT DEFINED LLAMA_INCLUDE_DIR OR NOT DEFINED LLAMA_GGML_INCLUDE_DIR OR NOT DEFINED LLAMA_LIBRARY_DIR)
    message(FATAL_ERROR "Pass LLAMA_INCLUDE_DIR, LLAMA_GGML_INCLUDE_DIR, and LLAMA_LIBRARY_DIR when configuring this project")
endif()

foreach(lib_name IN ITEMS llama ggml ggml-base ggml-cpu)
    add_library(${lib_name} SHARED IMPORTED)
    set_target_properties(${lib_name} PROPERTIES
        IMPORTED_LOCATION "${LLAMA_LIBRARY_DIR}/lib${lib_name}.so")
endforeach()

add_library(flash_inference SHARED flash_inference.cpp)
target_include_directories(flash_inference PRIVATE "${LLAMA_INCLUDE_DIR}" "${LLAMA_GGML_INCLUDE_DIR}")
target_link_libraries(flash_inference PRIVATE llama ggml ggml-base ggml-cpu android log)
