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

// Combined telemetry packet structure (must match transmitter - 60 bytes packed)
typedef struct __attribute__((packed)) {
    uint32_t magic;          // 4 bytes - 0x46533236 ("FS26")

    // GPS Data
    float    latitude;       // 4 bytes
    float    longitude;      // 4 bytes
    float    gps_speed_kph;  // 4 bytes
    float    altitude;       // 4 bytes
    uint8_t  satellites;     // 1 byte
    uint8_t  fix_valid;      // 1 byte

    // CAN Data - Engine Parameters
    uint16_t rpm;            // 2 bytes - RPM
    float    engine_temp;    // 4 bytes - degC
    float    tps;            // 4 bytes - Throttle Position %

    // CAN Data - Pressures & Fluids
    float    oil_pressure;   // 4 bytes - Bar
    float    fuel_pressure;  // 4 bytes - Bar
    float    brake_pressure; // 4 bytes - Bar
    float    battery_voltage;// 4 bytes - V

    // CAN Data - Wheel Speeds
    uint16_t wheel_speed_fr; // 2 bytes - km/h
    uint16_t wheel_speed_fl; // 2 bytes - km/h
    uint16_t wheel_speed_rr; // 2 bytes - km/h
    uint16_t wheel_speed_rl; // 2 bytes - km/h

    // CAN Data - Dynamics
    float    g_force_lateral; // 4 bytes
    float    heading;         // 4 bytes

    // Packet Metadata
    uint16_t tx_count;       // 2 bytes - LoRa TX count
    uint16_t can_frame_count; // 2 bytes - CAN frames received
} combined_telemetry_packet_t;

/*
 * -----------------------------------------------------------------------------
 * --- PRIVATE VARIABLES -------------------------------------------------------
 */

static volatile bool rx_done_flag = false;
static volatile bool rx_error_flag = false;
static uint32_t rx_count = 0;
static uint32_t error_count = 0;
static uint32_t header_error_count = 0;
static uint32_t crc_error_count = 0;
static uint32_t timeout_count = 0;
static uint32_t cad_done_count = 0;  // Channel Activity Detection without full RX

/*
 * -----------------------------------------------------------------------------
 * --- PRIVATE FUNCTIONS -------------------------------------------------------
 */

static void lora_hardware_reset(void) {
    printf("[LORA] Executing physical hardware reset...\n");
    gpio_init(RADIO_RESET);
    gpio_set_dir(RADIO_RESET, GPIO_OUT);
    
    // Pull NRESET low to kill the silicon state
    gpio_put(RADIO_RESET, 0);
    sleep_ms(20);
    // Bring it back high to boot
    gpio_put(RADIO_RESET, 1);
    
    // Give the internal PLLs time to stabilize
    sleep_ms(100); 
}

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
    
    // Log RX configuration for debugging
    printf("\nReceiver Configuration:\n");
    printf("   RF frequency  = %lu Hz\n", (unsigned long)RF_FREQ_IN_HZ);
    printf("   Payload length = %u bytes\n", PAYLOAD_LENGTH);
    printf("   Spreading factor = LR11XX_RADIO_LORA_SF7\n");
    printf("   Bandwidth        = LR11XX_RADIO_LORA_BW_800\n");
    printf("   Coding rate      = LR11XX_RADIO_LORA_CR_4_5\n");
    printf("   Preamble length = %u symbol(s)\n", LORA_PREAMBLE_LENGTH);
    printf("   Header mode     = LR11XX_RADIO_LORA_PKT_EXPLICIT\n");
    printf("   CRC mode        = LR11XX_RADIO_LORA_CRC_OFF\n");
    printf("   IQ              = LR11XX_RADIO_LORA_IQ_STANDARD\n");
    printf("   Sync word       = 0x%02X\n", LORA_SYNCWORD);
    printf("   RX boost        = %s\n\n", ENABLE_RX_BOOST_MODE ? "enabled" : "disabled");
    
    lora_init_irq(&lr1121, &rx_isr);

    ASSERT_LR11XX_RC(lr11xx_system_set_dio_irq_params(
        &lr1121,
        LR11XX_SYSTEM_IRQ_RX_DONE | LR11XX_SYSTEM_IRQ_CRC_ERROR | 
        LR11XX_SYSTEM_IRQ_TIMEOUT | LR11XX_SYSTEM_IRQ_HEADER_ERROR,
        0));
    ASSERT_LR11XX_RC(lr11xx_system_clear_irq_status(&lr1121, 0xFFFFFFFF));

    // Print any system error flags detected at init
    uint16_t sys_errors = 0;
    if (lr11xx_system_get_errors(&lr1121, &sys_errors) == LR11XX_STATUS_OK) {
        if (sys_errors != 0) {
            printf("[LORA] System errors at init: 0x%04X\n", sys_errors);
        } else {
            printf("[LORA] No system errors at init\n");
        }
    } else {
        printf("[LORA] Failed to read system errors at init\n");
    }

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
    ASSERT_LR11XX_RC(lr11xx_system_clear_irq_status(&lr1121, 0xFFFFFFFF));
    
    rx_done_flag = false;
    rx_error_flag = false;
    
    // Start reception (RX_CONTINUOUS = 0xFFFFFF for continuous mode)
    printf("[LORA] Starting RX (continuous)\n");
    printf("[DEBUG] Calling set_rx_with_timeout_in_rtc_step with RX_CONTINUOUS=0x%06X\n", RX_CONTINUOUS);
    
    lr11xx_status_t rc = lr11xx_radio_set_rx_with_timeout_in_rtc_step(&lr1121, RX_CONTINUOUS);
    if (rc != LR11XX_STATUS_OK) {
        printf("[DEBUG] ERROR: set_rx_with_timeout_in_rtc_step returned %d\n", rc);
    } else {
        printf("[DEBUG] set_rx_with_timeout_in_rtc_step success\n");
    }
    
    // Check radio state immediately after starting RX
    sleep_ms(10);
    lr11xx_system_irq_mask_t irq_check;
    lr11xx_system_get_irq_status(&lr1121, &irq_check);
    printf("[DEBUG] IRQ status immediately after RX start: 0x%08lX\n", (unsigned long)irq_check);
    
    int8_t rssi_check = 0;
    if (lr11xx_radio_get_rssi_inst(&lr1121, &rssi_check) == LR11XX_STATUS_OK) {
        printf("[DEBUG] RSSI check after RX start: %d dBm\n", rssi_check);
    }
    
    ASSERT_LR11XX_RC(rc);
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
    uint32_t poll_count = 0;
    // Wait for RX to complete
    while (!rx_done_flag) {
        // Check IRQ register directly as backup
        lr11xx_system_irq_mask_t irq_status;
        lr11xx_system_get_irq_status(&lr1121, &irq_status);
        
        // Exit ONLY on terminal events: RX_DONE, CRC_ERROR, TIMEOUT, or HEADER_ERROR
        if (irq_status & (LR11XX_SYSTEM_IRQ_RX_DONE | LR11XX_SYSTEM_IRQ_CRC_ERROR | 
                        LR11XX_SYSTEM_IRQ_TIMEOUT | LR11XX_SYSTEM_IRQ_HEADER_ERROR)) {
            rx_done_flag = true;
            
            if (irq_status & (LR11XX_SYSTEM_IRQ_CRC_ERROR | LR11XX_SYSTEM_IRQ_TIMEOUT | 
                            LR11XX_SYSTEM_IRQ_HEADER_ERROR)) {
                rx_error_flag = true;
            }
            break;
        }

        // If an IRQ fired but it wasn't expected, abort the wait.
        if (irq_status != 0 && !(irq_status & LR11XX_SYSTEM_IRQ_PREAMBLE_DETECTED) 
            && !(irq_status & LR11XX_SYSTEM_IRQ_SYNC_WORD_HEADER_VALID)) {
            
            printf("[LORA] Aborting RX wait due to unhandled error IRQ: 0x%08lX\n", (unsigned long)irq_status);
            rx_done_flag = true;
            rx_error_flag = true; 
            break;
        }

        // Periodic heartbeat while waiting: every ~1000 ms
        poll_count++;
        if ((poll_count % 1000) == 0) {
            int8_t inst_rssi = 0;
            lr11xx_system_get_irq_status(&lr1121, &irq_status);
            if (lr11xx_radio_get_rssi_inst(&lr1121, &inst_rssi) == LR11XX_STATUS_OK) {
                printf("[LORA] Heartbeat [%lu.%lus]: IRQ=0x%08lX, RSSI=%d dBm\n", poll_count/1000, (poll_count%1000)/100, (unsigned long)irq_status, inst_rssi);
            } else {
                printf("[LORA] Heartbeat [%lu.%lus]: IRQ=0x%08lX, RSSI=(err)\n", poll_count/1000, (poll_count%1000)/100, (unsigned long)irq_status);
            }
        }
        
        // Safety timeout: if stuck for 5 seconds, force exit
        if (poll_count > 5000) {
            printf("[LORA] Safety timeout after 5s (poll_count=%lu), forcing exit\n", poll_count);
            rx_done_flag = true;
            rx_error_flag = true;
            break;
        }

        sleep_ms(1);
    }
    
    // Get the IRQ status
    lr11xx_system_irq_mask_t irq_status;
    lr11xx_system_get_irq_status(&lr1121, &irq_status);
    
    // Debug: print raw IRQ status before clearing
    printf("[LORA] IRQ status: 0x%08lX\n", (unsigned long)irq_status);
    
    // Decode individual IRQ flags
    printf("[DEBUG] IRQ flags set:\n");
    if (irq_status & LR11XX_SYSTEM_IRQ_PREAMBLE_DETECTED) printf("  - PREAMBLE_DETECTED\n");
    if (irq_status & LR11XX_SYSTEM_IRQ_SYNC_WORD_HEADER_VALID) printf("  - SYNC_WORD_HEADER_VALID\n");
    if (irq_status & LR11XX_SYSTEM_IRQ_HEADER_ERROR) printf("  - HEADER_ERROR\n");
    if (irq_status & LR11XX_SYSTEM_IRQ_RX_DONE) printf("  - RX_DONE\n");
    if (irq_status & LR11XX_SYSTEM_IRQ_CRC_ERROR) printf("  - CRC_ERROR\n");
    if (irq_status & LR11XX_SYSTEM_IRQ_TIMEOUT) printf("  - TIMEOUT\n");
    if (irq_status & 0x10) printf("  - CAD_DONE (0x10) - Preamble detected but packet RX failed\n");
    if (irq_status == 0) printf("  - (no recognized flags)\n");
    if ((irq_status & 0xFFFFFFE0) != 0) printf("  - Other unknown bits: 0x%08lX\n", (unsigned long)(irq_status & 0xFFFFFFE0));

    // Extra handling: header / sync diagnostics
    if (irq_status & LR11XX_SYSTEM_IRQ_PREAMBLE_DETECTED) {
        printf("[LORA] Preamble detected\n");
    }
    if (irq_status & LR11XX_SYSTEM_IRQ_SYNC_WORD_HEADER_VALID) {
        printf("[LORA] Sync word / header valid\n");
    }
    if (irq_status & LR11XX_SYSTEM_IRQ_HEADER_ERROR) {
        header_error_count++;
        printf("[LORA] Header error detected (total: %lu)\n", header_error_count);

        // Dump RX buffer/header bytes for inspection
        lr11xx_radio_rx_buffer_status_t rx_buffer_status;
        if (lr11xx_radio_get_rx_buffer_status(&lr1121, &rx_buffer_status) == LR11XX_STATUS_OK) {
            printf("[LORA] RX buffer on header error: payload_len=%u start=%u\n", rx_buffer_status.pld_len_in_bytes, rx_buffer_status.buffer_start_pointer);
            uint8_t dump_len = rx_buffer_status.pld_len_in_bytes > 32 ? 32 : rx_buffer_status.pld_len_in_bytes;
            if (dump_len > 0) {
                uint8_t tmp[32];
                if (lr11xx_regmem_read_buffer8(&lr1121, tmp, rx_buffer_status.buffer_start_pointer, dump_len) == LR11XX_STATUS_OK) {
                    printf("[LORA] Header error dump: ");
                    for (uint8_t i = 0; i < dump_len; i++) printf("%02X ", tmp[i]);
                    printf("\n");
                }
            }
        }
        
        // Check system errors
        uint16_t sys_errors = 0;
        if (lr11xx_system_get_errors(&lr1121, &sys_errors) == LR11XX_STATUS_OK) {
            if (sys_errors != 0) {
                printf("[LORA] System errors on header error: 0x%04X\n", sys_errors);
            }
        }
        
        return false;
    }

    // Clear all IRQs
    ASSERT_LR11XX_RC(lr11xx_system_clear_irq_status(&lr1121, 0xFFFFFFFF));
    
    // Check for errors
    if (irq_status & LR11XX_SYSTEM_IRQ_CRC_ERROR) {
        crc_error_count++;
        printf("[LORA] CRC error (total: %lu)\n", crc_error_count);

        // Dump system error flags and RX buffer contents for debugging
        uint16_t sys_errors = 0;
        if (lr11xx_system_get_errors(&lr1121, &sys_errors) == LR11XX_STATUS_OK) {
            printf("[LORA] System errors: 0x%04X\n", sys_errors);
        }

        lr11xx_radio_rx_buffer_status_t rx_buffer_status;
        if (lr11xx_radio_get_rx_buffer_status(&lr1121, &rx_buffer_status) == LR11XX_STATUS_OK) {
            printf("[LORA] RX buffer: payload_len=%u start=%u\n", rx_buffer_status.pld_len_in_bytes, rx_buffer_status.buffer_start_pointer);
            uint8_t dump_len = rx_buffer_status.pld_len_in_bytes > 32 ? 32 : rx_buffer_status.pld_len_in_bytes;
            if (dump_len > 0) {
                uint8_t tmp[32];
                if (lr11xx_regmem_read_buffer8(&lr1121, tmp, rx_buffer_status.buffer_start_pointer, dump_len) == LR11XX_STATUS_OK) {
                    printf("[LORA] RX dump: ");
                    for (uint8_t i = 0; i < dump_len; i++) printf("%02X ", tmp[i]);
                    printf("\n");
                }
            }
        }
        return false;
    }
    
    if (irq_status & LR11XX_SYSTEM_IRQ_TIMEOUT) {
        timeout_count++;
        printf("[LORA] RX timeout (total: %lu)\n", timeout_count);

        // On timeout, also read system errors and RSSI instant to see if any energy was detected
        uint16_t sys_errors = 0;
        if (lr11xx_system_get_errors(&lr1121, &sys_errors) == LR11XX_STATUS_OK) {
            printf("[LORA] System errors: 0x%04X\n", sys_errors);
        }

        int8_t rssi_inst = 0;
        if (lr11xx_radio_get_rssi_inst(&lr1121, &rssi_inst) == LR11XX_STATUS_OK) {
            printf("[LORA] Instant RSSI: %d dBm\n", rssi_inst);
        }

        lr11xx_radio_rx_buffer_status_t rx_buffer_status;
        if (lr11xx_radio_get_rx_buffer_status(&lr1121, &rx_buffer_status) == LR11XX_STATUS_OK) {
            printf("[LORA] RX buffer after timeout: payload_len=%u start=%u\n", rx_buffer_status.pld_len_in_bytes, rx_buffer_status.buffer_start_pointer);
            uint8_t dump_len = rx_buffer_status.pld_len_in_bytes > 32 ? 32 : rx_buffer_status.pld_len_in_bytes;
            if (dump_len > 0) {
                uint8_t tmp[32];
                if (lr11xx_regmem_read_buffer8(&lr1121, tmp, rx_buffer_status.buffer_start_pointer, dump_len) == LR11XX_STATUS_OK) {
                    printf("[LORA] RX dump: ");
                    for (uint8_t i = 0; i < dump_len; i++) printf("%02X ", tmp[i]);
                    printf("\n");
                }
            }
        }
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
static void display_telemetry(const combined_telemetry_packet_t* packet, int8_t rssi, int8_t snr)
{
    printf("\n");
    printf("╔══════════════════════════════════════════════════════════════╗\n");
    printf("║            FS26 COMBINED TELEMETRY RECEIVED                 ║\n");
    printf("╠══════════════════════════════════════════════════════════════╣\n");
    printf("║  GPS:  %.6f, %.6f                                  ║\n", packet->latitude, packet->longitude);
    printf("║  GPS Spd: %.1f kph | Alt: %.1f m | Sat: %u | Fix: %s   ║\n",
        packet->gps_speed_kph, packet->altitude, packet->satellites,
        packet->fix_valid ? "Valid" : "No Fix");
    printf("║  RPM: %u | TPS: %.1f%% | Eng: %.1f C | Oil: %.2f Bar ║\n",
        packet->rpm, packet->tps, packet->engine_temp, packet->oil_pressure);
    printf("║  Fuel: %.2f Bar | Brake: %.2f Bar | Volt: %.2f V ║\n",
        packet->fuel_pressure, packet->brake_pressure, packet->battery_voltage);
    printf("║  Wheels FR/FL/RR/RL: %u/%u/%u/%u                 ║\n",
        packet->wheel_speed_fr, packet->wheel_speed_fl,
        packet->wheel_speed_rr, packet->wheel_speed_rl);
    printf("║  Lateral G: %.2f | Heading: %.1f deg              ║\n",
        packet->g_force_lateral, packet->heading);
    printf("║  TX Count: %u | CAN Frames: %u                     ║\n",
        packet->tx_count, packet->can_frame_count);
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

    // Receive buffer
    uint8_t rx_buffer[PAYLOAD_LENGTH];
    uint8_t rx_length;
    int8_t rssi, snr;
    
    printf("[LORA] Listening for combined GPS + CAN telemetry...\n");
    printf("[LORA] Frequency: %lu Hz\n", (unsigned long)RF_FREQ_IN_HZ);
    printf("[LORA] Radio configured payload length: %u bytes\n", PAYLOAD_LENGTH);
    printf("[LORA] Telemetry struct size: %lu bytes\n", (unsigned long)sizeof(combined_telemetry_packet_t));
    printf("[LORA] RX buffer size: %lu bytes\n", (unsigned long)sizeof(rx_buffer));
    printf("\n");
    
    // Main receive loop
    int consecutive_errors = 0; // NEW: Watchdog counter

    while (true) {
        // Start listening
        lora_start_rx();
        
        // Wait for packet
        if (lora_receive(rx_buffer, sizeof(rx_buffer), &rx_length, &rssi, &snr)) {
            consecutive_errors = 0; // Reset watchdog on a good packet!

            // Validate packet size against the combined telemetry payload
            if (rx_length >= sizeof(combined_telemetry_packet_t)) {
                combined_telemetry_packet_t* packet = (combined_telemetry_packet_t*)rx_buffer;
                
                // Validate magic number
                if (packet->magic == TELEMETRY_MAGIC) {
                    display_telemetry(packet, rssi, snr);
                } else {
                    printf("[LORA] Invalid magic...\n");
                }
            } 
        } else {
            consecutive_errors++;
            sleep_ms(5); // Give USB stack breathing room

            // The Self-Healing Trigger
            if (consecutive_errors >= 4) {
                printf("\n[FAULT] Radio state machine deadlocked. Watchdog triggered!\n");
                
                lora_hardware_reset(); // Nuke the silicon
                lora_rx_init();        // Reconfigure the radio
                
                consecutive_errors = 0;
            }
            // Print error statistics every 10 failures
            if (((header_error_count + crc_error_count + timeout_count) % 10) == 0 && 
                (header_error_count + crc_error_count + timeout_count) > 0) {
                printf("[STATS] RX Success: %lu | Header Errors: %lu | CRC Errors: %lu | Timeouts: %lu\n",
                       rx_count, header_error_count, crc_error_count, timeout_count);
            }
        }
        
        // Small delay before next receive cycle
        sleep_ms(10);
    }
    
    return 0;
}
