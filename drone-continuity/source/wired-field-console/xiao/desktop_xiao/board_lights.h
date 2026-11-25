#pragma once
#include "hardware/pwm.h"
#include "ws2812.pio.h"
#include "led_sideband.h"

class BoardLights {
    static constexpr uint RGB=22, POWER=23, YELLOW=25;
    int sm_=-1;
    uint32_t enabledAt_=0, next_=0;
    bool force_=true;
 public:
    lamps::Settings settings;
    lamps::Output applied;

    void begin(){
        static_assert(LED_BUILTIN==YELLOW,"Check XIAO user LED routing.");
        gpio_init(POWER);gpio_put(POWER,0);gpio_set_dir(POWER,true);
        gpio_init(YELLOW);gpio_put(YELLOW,1);gpio_set_dir(YELLOW,true);
        uint slice=pwm_gpio_to_slice_num(YELLOW);
        auto c=pwm_get_default_config();
        pwm_config_set_clkdiv(&c,128.0f);
        pwm_config_set_wrap(&c,255);
        pwm_init(slice,&c,false);
        pwm_set_gpio_level(YELLOW,256);   // active-low indicator, always high at reset
        gpio_set_function(YELLOW,GPIO_FUNC_PWM);
        pwm_set_enabled(slice,true);
        if(pio_can_add_program(pio0,&ws2812_program)){
            sm_=pio_claim_unused_sm(pio0,false);
            if(sm_>=0){
                uint offset=pio_add_program(pio0,&ws2812_program);
                ws2812_program_init(pio0,uint(sm_),offset,RGB,800000,false);
            }
        }
    }
    bool rgbReady() const {return sm_>=0;}
    void set(const lamps::Settings &s){settings=s;next_=0;}
    void tick(uint32_t now){
        if(next_ && int32_t(now-next_)<0)return;
        next_=now+2;
        auto desired=lamps::render(settings,now);
        if(desired.y!=applied.y){
            pwm_set_gpio_level(YELLOW,256u-uint(desired.y)*256u/255u);
            applied.y=desired.y;
        }
        if(!rgbReady())return;
        if(desired.power!=applied.power){
            gpio_put(POWER,desired.power!=0);
            applied.power=desired.power;applied.r=applied.g=applied.b=0;
            enabledAt_=now;force_=true;
        }
        if(!applied.power || now-enabledAt_<2 || pio_sm_is_tx_fifo_full(pio0,sm_))return;
        if(!force_ && desired.r==applied.r && desired.g==applied.g && desired.b==applied.b)return;
        const uint32_t grb=(uint32_t(desired.g)<<24)|(uint32_t(desired.r)<<16)|(uint32_t(desired.b)<<8);
        pio_sm_put(pio0,sm_,grb);
        applied.r=desired.r;applied.g=desired.g;applied.b=desired.b;force_=false;
    }
};
