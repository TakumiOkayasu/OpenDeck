cmake_minimum_required(VERSION 4.3)
project(OpenDeckMixedConsumer LANGUAGES C CXX)

set(OPENDECK_BUILD_PYTHON OFF CACHE BOOL "" FORCE)
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
add_subdirectory("${OPENDECK_SOURCE_DIR}" core)

add_executable(native_mixed_consumer main.cpp helper.c)
target_link_libraries(native_mixed_consumer PRIVATE opendeck_core)
