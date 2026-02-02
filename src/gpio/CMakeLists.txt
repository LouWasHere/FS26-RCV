# Search for all source files in the current directory
# and save the names to the DIR_GPIO_SRCS variable
aux_source_directory(. DIR_GPIO_SRCS)

# Generate link library
add_library(gpio ${DIR_GPIO_SRCS})
target_link_libraries(gpio PUBLIC pico_stdlib)