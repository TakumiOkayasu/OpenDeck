cmake_minimum_required(VERSION 4.3)
project(OpenDeck LANGUAGES CXX)

option(OPENDECK_BUILD_PYTHON "Build the Python extension" ON)

if(NOT CMAKE_CXX_COMPILER_ID STREQUAL "Clang"
   OR CMAKE_CXX_COMPILER_VERSION VERSION_LESS 23
   OR NOT CMAKE_CXX_COMPILER_FRONTEND_VARIANT STREQUAL "GNU")
    message(FATAL_ERROR
        "OpenDeck requires LLVM Clang 23+ (clang++) for C++23. "
        "Use mise exec -- cmake."
    )
endif()

set(CMAKE_CXX_EXTENSIONS OFF)

# Share the C++23 requirement with consumers and contract probes.
add_library(opendeck_dialect INTERFACE IMPORTED GLOBAL)
set_target_properties(opendeck_dialect PROPERTIES
    INTERFACE_COMPILE_FEATURES cxx_std_23
)

add_library(opendeck_core STATIC
    native/src/runtime.cpp
    native/src/recognition.cpp
    native/src/panel.cpp
)
target_link_libraries(opendeck_core PUBLIC opendeck_dialect)
target_include_directories(opendeck_core
    PUBLIC native/include
    PRIVATE native/private
)
set_target_properties(opendeck_core PROPERTIES
    CXX_EXTENSIONS OFF
    POSITION_INDEPENDENT_CODE ON
)

if(OPENDECK_BUILD_PYTHON)
    set(PYBIND11_FINDPYTHON ON)
    find_package(pybind11 CONFIG REQUIRED)
    pybind11_add_module(_native native/python/module.cpp)
    target_include_directories(_native PRIVATE native/private)
    target_link_libraries(_native PRIVATE opendeck_core)
    install(TARGETS _native DESTINATION opendeck)
endif()

include(CTest)
if(BUILD_TESTING)
    foreach(test_name IN ITEMS contracts runtime input)
        add_executable(native_${test_name} native/tests/${test_name}.cpp)
        target_link_libraries(native_${test_name} PRIVATE opendeck_core)
        add_test(NAME native_${test_name} COMMAND native_${test_name})
    endforeach()
    target_include_directories(native_input PRIVATE native/private)

    set(public_include_dir "${CMAKE_CURRENT_SOURCE_DIR}/native/include")
    function(check_contract probe expected_error)
        set(definitions)
        if(NOT probe STREQUAL "VALID")
            list(APPEND definitions -DOPENDECK_NEGATIVE_${probe})
        endif()
        try_compile(compiles
            SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/native/tests/contracts.cpp"
            NO_CACHE
            CMAKE_FLAGS
                "-DINCLUDE_DIRECTORIES=${public_include_dir}"
            COMPILE_DEFINITIONS ${definitions}
            LINK_LIBRARIES opendeck_dialect
            OUTPUT_VARIABLE output
        )
        if(probe STREQUAL "VALID")
            if(NOT compiles)
                message(FATAL_ERROR
                    "The valid contracts example must compile:\n${output}"
                )
            endif()
        elseif(compiles OR NOT output MATCHES "${expected_error}")
            message(FATAL_ERROR
                "The ${probe} probe must fail for its contract violation:\n"
                "${output}"
            )
        endif()
    endfunction()

    check_contract(VALID "")
    check_contract(ABSTRACT "abstract")
    check_contract(METHOD "no member named 'take'")
    check_contract(SIGNATURE "marked 'override'")

    try_compile(older_standard_compiles
        SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/native/tests/older_standard.cpp"
        NO_CACHE
        CMAKE_FLAGS
            "-DINCLUDE_DIRECTORIES=${public_include_dir}"
        CXX_STANDARD 20
        CXX_STANDARD_REQUIRED ON
        CXX_EXTENSIONS OFF
        OUTPUT_VARIABLE older_standard_output
    )
    if(older_standard_compiles)
        message(FATAL_ERROR
            "Public headers must reject older C++ language modes"
        )
    endif()
    if(NOT older_standard_output MATCHES "OpenDeck requires C[+][+]23")
        message(FATAL_ERROR
            "The older-mode probe failed for an unexpected reason:\n"
            "${older_standard_output}"
        )
    endif()
    get_filename_component(clang_directory "${CMAKE_CXX_COMPILER}" DIRECTORY)
    set(consumer_binary "${CMAKE_CURRENT_BINARY_DIR}/mixed-consumer")
    set(consumer_c_compiler
        "${clang_directory}/clang${CMAKE_EXECUTABLE_SUFFIX}"
    )
    set(consumer_executable
        "${consumer_binary}/native_mixed_consumer${CMAKE_EXECUTABLE_SUFFIX}"
    )
    add_test(NAME native_mixed_consumer
        COMMAND "${CMAKE_CTEST_COMMAND}"
            --build-and-test
                "${CMAKE_CURRENT_SOURCE_DIR}/native/tests/mixed_consumer"
                "${consumer_binary}"
            --build-generator "${CMAKE_GENERATOR}"
            --build-makeprogram "${CMAKE_MAKE_PROGRAM}"
            --build-options
                "-DOPENDECK_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}"
                "-DCMAKE_C_COMPILER=${consumer_c_compiler}"
                "-DCMAKE_CXX_COMPILER=${CMAKE_CXX_COMPILER}"
                "-DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE}"
            --test-command "${consumer_executable}"
    )
    message(STATUS "Verified C++23 mode and contract compile-failure probes")
endif()
