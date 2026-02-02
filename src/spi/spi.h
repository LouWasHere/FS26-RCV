/*****************************************************************************
 * | File         :   spi.h
 * | Author       :   Waveshare team
 * | Function     :   Hardware underlying interface
 * | Info         :
 * |                 SPI driver code for SPI communication.
 * ----------------
 * | This version :   V1.0
 * | Date         :   2024-11-26
 * | Info         :   Basic version
 *
 ******************************************************************************/

#ifndef __SPI_H
#define __SPI_H
#include "gpio.h"
#include "hardware/spi.h"

// SPI Defines
// We are going to use SPI 0, and allocate it to the following GPIO pins
// Pins can be changed, see the GPIO function select table in the datasheet for information on GPIO assignments
#define SPI_PORT spi1

void DEV_SPI_Init();

void DEV_SPI_Write_Bytes(const uint8_t* tx_buf, size_t length);
void DEV_SPI_Read_Bytes(uint8_t* rx_buf, size_t length);

#endif
