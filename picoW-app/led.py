from machine import Pin, PWM


class Led:
    FREQUENCY = 1000
    LED_BRIGHTNESS = 10000

    def __init__(self, pin):
        self.pin = pin
        self.led = Pin(self.pin, Pin.OUT)
        self.led_pwm = PWM(self.led)
        self.led_pwm.freq(Led.FREQUENCY)

    def toggle_led(self):
        self.led.value(not self.led.value())

    def led_on(self):
        self.set_brightness(Led.LED_BRIGHTNESS)

    def led_off(self):
        self.set_brightness(0)

    def set_brightness(self, duty_cycle):
        """
        Set the brightness of the LED using PWM.
        :param duty_cycle: Duty cycle value (0-65535 for Pico)
        """
        if 0 <= duty_cycle <= 65535:
            self.led_pwm.duty_u16(duty_cycle)  # Scale to 16-bit (0-65535)
        else:
            raise ValueError("Duty cycle must be between 0 and 65535.")

