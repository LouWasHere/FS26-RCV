# Search for all source files in the current directory
# and save the names to the DIR_SPI_SRCS variable
aux_source_directory(. DIR_SPI_SRCS)

include_directories(../gpio)
# Generate link library
add_library(spi ${DIR_SPI_SRCS})
target_link_libraries(spi PUBLIC gpio hardware_spi)