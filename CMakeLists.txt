cmake_minimum_required(VERSION 3.26)
project(OpenDeck LANGUAGES CXX)

option(OPENDECK_BUILD_PYTHON "Build the Python extension" ON)

add_library(opendeck_core STATIC
    native/src/runtime.cpp
    native/src/recognition.cpp
    native/src/panel.cpp
)
target_compile_features(opendeck_core PUBLIC cxx_std_20)
target_include_directories(opendeck_core PUBLIC native/include PRIVATE native/private)
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

    set(contract_source "${CMAKE_CURRENT_SOURCE_DIR}/native/tests/contracts.cpp")
    try_compile(contracts_compile
        SOURCES "${contract_source}"
        CMAKE_FLAGS "-DINCLUDE_DIRECTORIES=${CMAKE_CURRENT_SOURCE_DIR}/native/include"
        CXX_STANDARD 20
        CXX_STANDARD_REQUIRED ON
        CXX_EXTENSIONS OFF
        OUTPUT_VARIABLE contract_output
    )
    if(NOT contracts_compile)
        message(FATAL_ERROR "The valid contracts example must compile:\n${contract_output}")
    endif()

    foreach(probe IN ITEMS ABSTRACT METHOD SIGNATURE)
        try_compile(contracts_${probe}_compile
            SOURCES "${contract_source}"
            CMAKE_FLAGS "-DINCLUDE_DIRECTORIES=${CMAKE_CURRENT_SOURCE_DIR}/native/include"
            COMPILE_DEFINITIONS -DOPENDECK_NEGATIVE_${probe}
            CXX_STANDARD 20
            CXX_STANDARD_REQUIRED ON
            CXX_EXTENSIONS OFF
        )
        if(contracts_${probe}_compile)
            message(FATAL_ERROR "The invalid ${probe} contracts example must fail to compile")
        endif()
    endforeach()
endif()
