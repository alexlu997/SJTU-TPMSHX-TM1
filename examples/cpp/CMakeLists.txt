cmake_minimum_required(VERSION 3.31.8)
project(tpmshx_external_consumer LANGUAGES CXX)
enable_testing()

find_package(tpmshx CONFIG REQUIRED)
if("result" IN_LIST tpmshx_AVAILABLE_COMPONENTS)
    find_package(tpmshx CONFIG REQUIRED COMPONENTS result)
    add_executable(result_client result_client.cpp)
    target_compile_features(result_client PRIVATE cxx_std_17)
    target_link_libraries(result_client PRIVATE tpmshx::result)
    add_test(NAME result_client COMMAND result_client)
    if(WIN32)
        add_custom_command(TARGET result_client POST_BUILD
            COMMAND "${CMAKE_COMMAND}" -E copy_if_different
                "$<TARGET_FILE:tpmshx::result>" "$<TARGET_FILE_DIR:result_client>")
    endif()
endif()

if("preparation" IN_LIST tpmshx_AVAILABLE_COMPONENTS AND "solver" IN_LIST tpmshx_AVAILABLE_COMPONENTS
    AND "result" IN_LIST tpmshx_AVAILABLE_COMPONENTS)
    find_package(tpmshx CONFIG REQUIRED COMPONENTS preparation solver)
    add_executable(air_2d air_2d.cpp)
    target_compile_features(air_2d PRIVATE cxx_std_17)
    target_link_libraries(air_2d PRIVATE tpmshx::preparation tpmshx::solver tpmshx::result)
    add_test(NAME air_2d COMMAND air_2d)
    if(WIN32)
        foreach(component IN ITEMS preparation solver result)
            add_custom_command(TARGET air_2d POST_BUILD
                COMMAND "${CMAKE_COMMAND}" -E copy_if_different
                    "$<TARGET_FILE:tpmshx::${component}>" "$<TARGET_FILE_DIR:air_2d>")
        endforeach()
    endif()
endif()

if("preparation" IN_LIST tpmshx_AVAILABLE_COMPONENTS)
    find_package(tpmshx CONFIG REQUIRED COMPONENTS preparation)
    add_executable(prepare_fluids_2d prepare_fluids_2d.cpp)
    target_compile_features(prepare_fluids_2d PRIVATE cxx_std_17)
    target_link_libraries(prepare_fluids_2d PRIVATE tpmshx::preparation)
    add_test(NAME prepare_fluids_2d COMMAND prepare_fluids_2d)
    if(WIN32)
        add_custom_command(TARGET prepare_fluids_2d POST_BUILD
            COMMAND "${CMAKE_COMMAND}" -E copy_if_different
                "$<TARGET_FILE:tpmshx::preparation>" "$<TARGET_FILE_DIR:prepare_fluids_2d>")
    endif()
endif()
