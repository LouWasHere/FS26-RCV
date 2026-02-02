# lr1121_lib/CMakeLists.txt
# Used to build a static library named lr1121

# Recursively gather all .c source files
file(GLOB_RECURSE LR1121_SRC 
    ${CMAKE_CURRENT_SOURCE_DIR}/*.c
    ${CMAKE_CURRENT_SOURCE_DIR}/lr1121_printers/*.c
    ${CMAKE_CURRENT_SOURCE_DIR}/lr1121_modem/*.c 
    ${CMAKE_CURRENT_SOURCE_DIR}/lr1121_common/*.c
    ${CMAKE_CURRENT_SOURCE_DIR}/lr11xx_driver/*.c
)

# Create a static library
add_library(lr1121 STATIC ${LR1121_SRC})

# Set include directories
target_include_directories(lr1121 PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/lr1121_printers
    ${CMAKE_CURRENT_SOURCE_DIR}/lr1121_modem
    ${CMAKE_CURRENT_SOURCE_DIR}/lr1121_common
    ${CMAKE_CURRENT_SOURCE_DIR}/lr11xx_driver
)

include_directories(../gpio)
include_directories(../spi)

# Link to Pico SDK modules (for use by applications that link this library)
target_link_libraries(lr1121 PUBLIC
    pico_stdlib
    gpio
    spi
    hardware_timer
)
