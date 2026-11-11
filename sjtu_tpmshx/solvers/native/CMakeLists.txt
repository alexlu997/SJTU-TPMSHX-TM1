cmake_minimum_required(VERSION 3.31.8)
project(tpmshx LANGUAGES C CXX)

include(ExternalProject)
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

set(TPMSHX_NATIVE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}")
get_filename_component(TPMSHX_ROOT "${TPMSHX_NATIVE_ROOT}/../../.." ABSOLUTE)
set(TPMSHX_NATIVE_DEPS_ROOT "${TPMSHX_ROOT}/.cache/native-deps" CACHE PATH "Locked dependency cache")
set(TPMSHX_MODEL_INCLUDE_DIR "${TPMSHX_NATIVE_DEPS_ROOT}/generated" CACHE PATH "Generated model headers")
set(TPMSHX_SOLVER_COOLPROP_LIBRARY "" CACHE FILEPATH "Locked solver CoolProp archive")
set(TPMSHX_PREPARATION_COOLPROP_LIBRARY "" CACHE FILEPATH "Locked preparation CoolProp archive")
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(default_components result)
else()
    set(default_components geometry preparation solver result)
endif()
set(TPMSHX_COMPONENTS "${default_components}" CACHE STRING "Native components to build and install")

if(NOT TPMSHX_COMPONENTS)
    message(FATAL_ERROR "Select at least one native component")
endif()
foreach(component IN LISTS TPMSHX_COMPONENTS)
    if(NOT component MATCHES "^(geometry|preparation|solver|result)$")
        message(FATAL_ERROR "Unknown native component: ${component}")
    endif()
    if(CMAKE_SYSTEM_NAME STREQUAL "Linux" AND NOT component STREQUAL "result")
        message(FATAL_ERROR "Linux supports only the result component")
    endif()
    set(source "${TPMSHX_NATIVE_ROOT}/${component}")
    set(options "-DTPMSHX_NATIVE_DEPS_ROOT:PATH=${TPMSHX_NATIVE_DEPS_ROOT}"
        "-DTPMSHX_MODEL_INCLUDE_DIR:PATH=${TPMSHX_MODEL_INCLUDE_DIR}"
        "-DCMAKE_BUILD_TYPE:STRING=Release")
    if(APPLE)
        list(APPEND options "-DCMAKE_OSX_ARCHITECTURES:STRING=arm64")
    endif()
    if(component STREQUAL "solver")
        set(source "${TPMSHX_NATIVE_ROOT}/dependency-pilot")
        list(APPEND options "-DTPMSHX_COOLPROP_LIBRARY:FILEPATH=${TPMSHX_SOLVER_COOLPROP_LIBRARY}")
    elseif(component STREQUAL "preparation")
        list(APPEND options "-DTPMSHX_COOLPROP_LIBRARY:FILEPATH=${TPMSHX_PREPARATION_COOLPROP_LIBRARY}")
    endif()
    string(TOUPPER "${component}" upper_component)
    set(TPMSHX_${upper_component}_BUILD_DIR "${CMAKE_BINARY_DIR}/${component}" CACHE PATH
        "Existing or new ${component} component build directory")
    set(component_build "${TPMSHX_${upper_component}_BUILD_DIR}")
    # Separate CMake scopes keep the two CoolProp archives and registries apart.
    ExternalProject_Add(tpmshx_${component}_build
        SOURCE_DIR "${source}" BINARY_DIR "${component_build}"
        DOWNLOAD_COMMAND "" UPDATE_COMMAND ""
        CMAKE_ARGS ${options}
        BUILD_COMMAND "${CMAKE_COMMAND}" --build <BINARY_DIR> --config Release
            --target tpmshx_${component}_shared --parallel 2
        BUILD_ALWAYS TRUE INSTALL_COMMAND "")
    set(library "${CMAKE_SHARED_LIBRARY_PREFIX}tpmshx_${component}_shared${CMAKE_SHARED_LIBRARY_SUFFIX}")
    if(WIN32)
        install(FILES "${component_build}/${library}" DESTINATION "${CMAKE_INSTALL_BINDIR}")
        install(FILES "${component_build}/Release/tpmshx_${component}_shared.lib"
            DESTINATION "${CMAKE_INSTALL_LIBDIR}")
    else()
        install(FILES "${component_build}/${library}" DESTINATION "${CMAKE_INSTALL_LIBDIR}")
    endif()
endforeach()

install(DIRECTORY "${TPMSHX_NATIVE_ROOT}/include/tpmshx" DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
    FILES_MATCHING PATTERN "*.h")
install(FILES "${TPMSHX_NATIVE_ROOT}/include/tpmshx/stages.hpp" DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}/tpmshx")
configure_package_config_file("${TPMSHX_NATIVE_ROOT}/cmake/tpmshxConfig.cmake.in"
    "${CMAKE_BINARY_DIR}/tpmshxConfig.cmake"
    INSTALL_DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/tpmshx"
    PATH_VARS CMAKE_INSTALL_INCLUDEDIR CMAKE_INSTALL_BINDIR CMAKE_INSTALL_LIBDIR)
install(FILES "${CMAKE_BINARY_DIR}/tpmshxConfig.cmake"
    DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/tpmshx")
install(FILES "${TPMSHX_ROOT}/LICENSE" DESTINATION "${CMAKE_INSTALL_DATADIR}/tpmshx")
install(FILES "${TPMSHX_NATIVE_ROOT}/THIRD_PARTY_NOTICES.md"
    "${TPMSHX_NATIVE_ROOT}/dependencies-lock.toml" DESTINATION "${CMAKE_INSTALL_DATADIR}/tpmshx")
install(DIRECTORY "${TPMSHX_NATIVE_ROOT}/licenses" DESTINATION "${CMAKE_INSTALL_DATADIR}/tpmshx")
foreach(directory IN ITEMS geometry preparation result)
    install(DIRECTORY "${TPMSHX_NATIVE_ROOT}/${directory}/"
        DESTINATION "${CMAKE_INSTALL_DATADIR}/tpmshx/${directory}" FILES_MATCHING PATTERN "*.md")
endforeach()
