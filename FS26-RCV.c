/*!
 * @file      receiver.c
 *
 * @brief     LoRa GPS Telemetry Receiver for LR1121 + Pico
 *            Receives GPS telemetry packets from FS26 DAQ transmitter
 *
 * @note      Move this file to a separate project for the receiver Pico
 */

#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "lr1121_config.h"

/*
 * -----------------------------------------------------------------------------
 * --- CONSTANTS ---------------------------------------------------------------
 */

#define TELEMETRY_MAGIC 0x46533236  // "FS26" in ASCII hex

/*
 * -----------------------------------------------------------------------------
 * --- TYPES -------------------------------------------------------------------
 */

// GPS telemetry packet structure (must match transmitter - 24 bytes packed)
typedef struct __attribute__((packed)) {
    uint32_t magic;         // 4 bytes - 0x46533236 ("FS26")
    float    latitude;      // 4 bytes
    float    longitude;     // 4 bytes
    float    speed_kph;     // 4 bytes
    float    altitude;      // 4 bytes
    uint16_t tx_count;      // 2 bytes
    uint8_t  satellites;    // 1 byte
    uint8_t  fix_valid;     // 1 byte
} gps_telemetry_packet_t;

/*
 * -----------------------------------------------------------------------------
 * --- PRIVATE VARIABLES -------------------------------------------------------
 */

static volatile bool rx_done_flag = false;
static volatile bool rx_error_flag = false;
static uint32_t rx_count = 0;
static uint32_t error_count = 0;

/*
 * -----------------------------------------------------------------------------
 * --- PRIVATE FUNCTIONS -------------------------------------------------------
 */

/**
 * @brief GPIO interrupt handler for LR1121 DIO
 */
static void rx_isr(uint gpio, uint32_t events) {
    rx_done_flag = true;
}

/**
 * @brief Initialize the LR1121 radio for RX-only operation
 */
static void lora_rx_init(void)
{
    printf("[LORA] Initializing LR1121 for RX...\n");
    
    lora_init_io_context(&lr1121);
    lora_init_io(&lr1121);
    lora_spi_init(&lr1121);

    printf("[LORA] LR11XX driver version: %s\n", lr11xx_driver_version_get_version_string());

    lora_system_init(&lr1121);
    lora_print_version(&lr1121);
    lora_radio_init(&lr1121);
    
    lora_init_irq(&lr1121, &rx_isr);

    // Enable RX_DONE and RX error interrupts
    ASSERT_LR11XX_RC(lr11xx_system_set_dio_irq_params(
        &lr1121, 
        LR11XX_SYSTEM_IRQ_RX_DONE | LR11XX_SYSTEM_IRQ_CRC_ERROR | LR11XX_SYSTEM_IRQ_TIMEOUT,
        0
    ));
    ASSERT_LR11XX_RC(lr11xx_system_clear_irq_status(&lr1121, LR11XX_SYSTEM_IRQ_ALL_MASK));

    printf("[LORA] RX initialization complete\n");
}

/**
 * @brief Start continuous receive mode
 */
static void lora_start_rx(void)
{
    // Ensure radio is in standby before RX
    ASSERT_LR11XX_RC(lr11xx_system_set_standby(&lr1121, LR11XX_SYSTEM_STANDBY_CFG_RC));
    
    // Clear any pending IRQs
    ASSERT_LR11XX_RC(lr11xx_system_clear_irq_status(&lr1121, LR11XX_SYSTEM_IRQ_ALL_MASK));
    
    rx_done_flag = false;
    rx_error_flag = false;
    
    // Start reception (RX_CONTINUOUS = 0xFFFFFF for continuous mode)
    ASSERT_LR11XX_RC(lr11xx_radio_set_rx(&lr1121, RX_CONTINUOUS));
}

/**
 * @brief Receive data over LoRa (blocking until packet received)
 * 
 * @param buffer Pointer to buffer to store received data
 * @param max_length Maximum buffer size
 * @param received_length Pointer to store actual received length
 * @param rssi Pointer to store RSSI value (can be NULL)
 * @param snr Pointer to store SNR value (can be NULL)
 * @return true if packet received successfully, false on error/timeout
 */
static bool lora_receive(uint8_t* buffer, uint8_t max_length, uint8_t* received_length, 
                         int8_t* rssi, int8_t* snr)
{
    // Wait for RX to complete
    while (!rx_done_flag) {
        // Check IRQ register directly as backup
        lr11xx_system_irq_mask_t irq_status;
        lr11xx_system_get_irq_status(&lr1121, &irq_status);
        
        if (irq_status & (LR11XX_SYSTEM_IRQ_RX_DONE | LR11XX_SYSTEM_IRQ_CRC_ERROR | LR11XX_SYSTEM_IRQ_TIMEOUT)) {
            rx_done_flag = true;
            
            if (irq_status & (LR11XX_SYSTEM_IRQ_CRC_ERROR | LR11XX_SYSTEM_IRQ_TIMEOUT)) {
                rx_error_flag = true;
            }
            break;
        }
        
        sleep_ms(1);
    }
    
    // Get the IRQ status
    lr11xx_system_irq_mask_t irq_status;
    lr11xx_system_get_irq_status(&lr1121, &irq_status);
    
    // Clear all IRQs
    ASSERT_LR11XX_RC(lr11xx_system_clear_irq_status(&lr1121, LR11XX_SYSTEM_IRQ_ALL_MASK));
    
    // Check for errors
    if (irq_status & LR11XX_SYSTEM_IRQ_CRC_ERROR) {
        error_count++;
        printf("[LORA] CRC error (total errors: %lu)\n", error_count);
        return false;
    }
    
    if (irq_status & LR11XX_SYSTEM_IRQ_TIMEOUT) {
        printf("[LORA] RX timeout\n");
        return false;
    }
    
    if (!(irq_status & LR11XX_SYSTEM_IRQ_RX_DONE)) {
        printf("[LORA] Unknown IRQ: 0x%08lX\n", (unsigned long)irq_status);
        return false;
    }
    
    // Get packet status for RSSI/SNR
    lr11xx_radio_pkt_status_lora_t pkt_status;
    ASSERT_LR11XX_RC(lr11xx_radio_get_lora_pkt_status(&lr1121, &pkt_status));
    
    if (rssi != NULL) {
        *rssi = pkt_status.rssi_pkt_in_dbm;
    }
    if (snr != NULL) {
        *snr = pkt_status.snr_pkt_in_db;
    }
    
    // Get received data length
    lr11xx_radio_rx_buffer_status_t rx_buffer_status;
    ASSERT_LR11XX_RC(lr11xx_radio_get_rx_buffer_status(&lr1121, &rx_buffer_status));
    
    uint8_t payload_len = rx_buffer_status.pld_len_in_bytes;
    if (payload_len > max_length) {
        printf("[LORA] Packet too large: %d > %d\n", payload_len, max_length);
        return false;
    }
    
    *received_length = payload_len;
    
    // Read the payload
    ASSERT_LR11XX_RC(lr11xx_regmem_read_buffer8(&lr1121, buffer, rx_buffer_status.buffer_start_pointer, payload_len));
    
    rx_count++;
    return true;
}

/**
 * @brief Parse and display GPS telemetry packet
 */
static void display_telemetry(const gps_telemetry_packet_t* packet, int8_t rssi, int8_t snr)
{
    printf("\n");
    printf("╔══════════════════════════════════════════════════════════════╗\n");
    printf("║              FS26 GPS TELEMETRY RECEIVED                     ║\n");
    printf("╠══════════════════════════════════════════════════════════════╣\n");
    printf("║  Position:   %.6f, %.6f                     ║\n", packet->latitude, packet->longitude);
    printf("║  Speed:      %.1f kph                                        ║\n", packet->speed_kph);
    printf("║  Altitude:   %.1f m                                          ║\n", packet->altitude);
    printf("║  Satellites: %d                                              ║\n", packet->satellites);
    printf("║  GPS Fix:    %s                                            ║\n", packet->fix_valid ? "Valid" : "No Fix");
    printf("║  TX Count:   %u                                              ║\n", packet->tx_count);
    printf("╠══════════════════════════════════════════════════════════════╣\n");
    printf("║  RSSI: %d dBm  |  SNR: %d dB  |  RX Count: %lu              ║\n", rssi, snr, rx_count);
    printf("╚══════════════════════════════════════════════════════════════╝\n");
}

/*
 * -----------------------------------------------------------------------------
 * --- MAIN --------------------------------------------------------------------
 */

int main()
{
    // Initialize stdio
    stdio_init_all();
    sleep_ms(2000);  // Wait for USB serial connection
    
    printf("\n");
    printf("========================================\n");
    printf("  FS26 GPS Telemetry Receiver\n");
    printf("  LR1121 LoRa @ 2.4GHz\n");
    printf("========================================\n");
    printf("\n");
    
    // Initialize LoRa receiver
    lora_rx_init();
    
    printf("[LORA] Listening for GPS telemetry...\n");
    printf("[LORA] Frequency: %lu Hz\n", (unsigned long)RF_FREQ_IN_HZ);
    printf("[LORA] Expected packet size: %lu bytes\n", (unsigned long)sizeof(gps_telemetry_packet_t));
    printf("\n");
    
    // Receive buffer
    uint8_t rx_buffer[PAYLOAD_LENGTH];
    uint8_t rx_length;
    int8_t rssi, snr;
    
    // Main receive loop
    while (true) {
        // Start listening
        lora_start_rx();
        
        // Wait for packet
        if (lora_receive(rx_buffer, sizeof(rx_buffer), &rx_length, &rssi, &snr)) {
            // Validate packet size (accept packets >= expected size for forward compatibility)
            if (rx_length >= sizeof(gps_telemetry_packet_t)) {
                gps_telemetry_packet_t* packet = (gps_telemetry_packet_t*)rx_buffer;
                
                // Validate magic number
                if (packet->magic == TELEMETRY_MAGIC) {
                    display_telemetry(packet, rssi, snr);
                } else {
                    printf("[LORA] Invalid magic: 0x%08lX (expected 0x%08lX)\n", 
                           (unsigned long)packet->magic, (unsigned long)TELEMETRY_MAGIC);
                }
            } else {
                printf("[LORA] Packet too small: %d bytes (expected >= %lu)\n", 
                       rx_length, (unsigned long)sizeof(gps_telemetry_packet_t));
                
                // Print hex dump for debugging
                printf("[LORA] Hex dump: ");
                for (int i = 0; i < rx_length && i < 32; i++) {
                    printf("%02X ", rx_buffer[i]);
                }
                printf("\n");
            }
        }
        
        // Small delay before next receive cycle
        sleep_ms(10);
    }
    
    return 0;
}
