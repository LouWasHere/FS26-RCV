#include "wavesahre_lora_1121.h"


void lora_init_io_context(const void *context)
{
    ((lr1121_t *)context)->reset = RADIO_RESET;
    ((lr1121_t *)context)->led = RADIO_LED;
    ((lr1121_t *)context)->cs = RADIO_CS;
    ((lr1121_t *)context)->irq = RADIO_IRQ;
    ((lr1121_t *)context)->busy = RADIO_BUSY;
    ((lr1121_t *)context)->miso = RADIO_MISO;
    ((lr1121_t *)context)->mosi = RADIO_MOSI;
    ((lr1121_t *)context)->clk = RADIO_CLK;
}

void lora_init_io(const void *context)
{
    DEV_GPIO_Mode(((lr1121_t *)context)->reset, GPIO_OUT);
    DEV_GPIO_Mode(((lr1121_t *)context)->cs, GPIO_OUT);
    DEV_GPIO_Mode(((lr1121_t *)context)->led, GPIO_OUT);
    DEV_GPIO_Mode(((lr1121_t *)context)->busy, GPIO_IN);
    DEV_GPIO_Mode(((lr1121_t *)context)->irq, GPIO_IN);

    DEV_Digital_Write(((lr1121_t *)context)->reset, 1 );
    DEV_Digital_Write(((lr1121_t *)context)->led, 1 );
    DEV_Digital_Write(((lr1121_t *)context)->cs, 1 );
}

void lora_init_irq(const void *context, gpio_irq_callback_t handler)
{
    DEV_GPIO_INT(((lr1121_t *)context)->irq, handler);
}

void lora_spi_init(const void* context)
{
    // Initialize the SPI interface and configure it for IO EXTENSION communication
    DEV_SPI_Init();
}

void lora_spi_write_bytes(const void* context,const uint8_t *wirte,const uint16_t wirte_length)
{
    DEV_SPI_Write_Bytes(wirte, wirte_length);
}

void lora_spi_read_bytes(const void* context, uint8_t *read,const uint16_t read_length)
{
    DEV_SPI_Read_Bytes(read, read_length);
}


lr1121_modem_response_code_t lr1121_modem_board_event_flush( const void* context )
{
    lr1121_modem_response_code_t modem_response_code = LR1121_MODEM_RESPONSE_CODE_OK;
    lr1121_modem_event_fields_t  event_fields;

    do
    {
        modem_response_code = lr1121_modem_get_event( context, &event_fields );
    } while( modem_response_code != LR1121_MODEM_RESPONSE_CODE_NO_EVENT );

    return modem_response_code;
}

