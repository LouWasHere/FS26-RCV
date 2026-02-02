/*****************************************************************************
 * | File         :   spi.c
 * | Author       :   Waveshare team
 * | Function     :   Hardware underlying interface
 * | Info         :
 * |                 SPI driver code for SPI communication.
 * ----------------
 * | This version :   V1.0
 * | Date         :   2025-06-23
 * | Info         :   Basic version
 *
 ******************************************************************************/

#include "spi.h"  // Include SPI driver header for I2C functions

void DEV_SPI_Init()
{
    // SPI initialisation. This example will use SPI at 1MHz.
    spi_init(SPI_PORT, 10*1000*1000);
    gpio_set_function(RADIO_MISO, GPIO_FUNC_SPI);
    gpio_set_function(RADIO_CS,   GPIO_FUNC_SIO);
    gpio_set_function(RADIO_CLK,  GPIO_FUNC_SPI);
    gpio_set_function(RADIO_MOSI, GPIO_FUNC_SPI);
}


void DEV_SPI_Write_Bytes(const uint8_t* tx_buf, size_t length)
{
    spi_write_blocking(SPI_PORT, tx_buf, length);
}

void DEV_SPI_Read_Bytes(uint8_t* rx_buf, size_t length)
{
    spi_read_blocking(SPI_PORT, 0x00, rx_buf, length);
}
