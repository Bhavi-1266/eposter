cmake_minimum_required(VERSION 3.16)
# Keep separate configurations when building both targets in the same checkout.
set(SDKCONFIG "${CMAKE_BINARY_DIR}/sdkconfig")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
idf_build_set_property(MINIMAL_BUILD ON)
project(radxa_remote)

# Include the board selected in data/setup.json in the regular IDF flash operation.
idf_build_get_property(idf_python PYTHON)
set(pair_image "${CMAKE_BINARY_DIR}/paircfg.bin")
add_custom_target(remote_pair ALL
    COMMAND "${idf_python}" "${CMAKE_CURRENT_SOURCE_DIR}/setup_board.py" partition
            --target "${IDF_TARGET}" --output "${pair_image}"
    BYPRODUCTS "${pair_image}"
    VERBATIM)
add_dependencies(flash remote_pair)
esptool_py_flash_to_partition(flash "paircfg" "${pair_image}")
