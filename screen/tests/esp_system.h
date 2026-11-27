#pragma once
#include <stddef.h>
#include <stdint.h>
enum { ESP_OK=0 };
int esp_efuse_mac_get_default(uint8_t *buf);
void esp_fill_random(void* buf,size_t n);
