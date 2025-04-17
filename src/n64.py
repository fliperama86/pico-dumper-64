
from machine import Pin, UART
from utime import sleep_us, sleep_ms
from time import sleep
import sys

# Constants
rom_base_address = 0x10000000
led_pin = Pin("LED", Pin.OUT)

# Pin configurations
# pico_pins_map = [28, 27, 26, 22, 21, 20, 19, 18, 9, 8, 7, 6, 5, 4, 3, 2]
pico_pins_map = [0, 1, 2, 3, 4, 5, 6, 7, 15, 14, 13, 12, 11, 10, 9, 8]
address_pins = [Pin(i, Pin.OUT) for i in pico_pins_map]

write_pin = Pin(20, Pin.OUT)
read_pin = Pin(19, Pin.OUT)

ale_low_pin = Pin(27, Pin.OUT)
ale_high_pin = Pin(26, Pin.OUT)

reset_pin = Pin(16, Pin.OUT)

# Setup UART for USB communication
uart = UART(0, baudrate=115200)

def setup_cart():
  # Set Address Pins to Output and set them low
  set_pico_address_pins_out()
  
  # Set Control Pins to Output RESET(PH0) WR(PH5) RD(PH6) aleL(PC0) aleH(PC1)
  for pin in [reset_pin, write_pin, read_pin, ale_low_pin, ale_high_pin]:
    pin.init(Pin.OUT)

  # Pull RESET(PH0) low until we are ready
  reset_pin.low()
  
  # Output a high signal on WR(PH5) RD(PH6), pins are active low therefore
  # everything is disabled now
  write_pin.high()
  read_pin.high()
  
  # Pull aleL(PC0) low and aleH(PC1) high
  ale_low_pin.low()
  ale_high_pin.high()
  
  # Wait until all is stable
  sleep_us(1)
  
  # Pull RESET(PH0) high to start eeprom
  reset_pin.high()

def set_pico_address_pins_out():
  for pin in address_pins:
    pin.init(Pin.OUT)
    pin.low()

def set_pico_address_pins_in():
  for pin in address_pins:
    pin.init(Pin.IN)

def set_address(address):
  # Set address pins to output
  set_pico_address_pins_out()

  # Split address into two words
  address_low = address & 0xFFFF
  address_high = address >> 16

  # Switch WR(PH5) RD(PH6) ale_L(PC0) ale_H(PC1) to high (since the pins are active low)
  write_pin.high()
  read_pin.high()
  ale_low_pin.high()
  ale_high_pin.high()
  
  write_word(address_high)

  ale_high_pin.low()

  write_word(address_low)
  
  ale_low_pin.low()
  
  set_pico_address_pins_in()

def read_word_from_address_pins():
  word = 0
  for i in range(16):
    bit = address_pins[i].value()
    word |= bit << i
  return word

def write_word(word):
  for i in range(16):
    bit = (word >> i) & 1
    address_pins[i].value(bit)

def read_word():
  read_pin.low()
  word = read_word_from_address_pins()
  read_pin.high()
  return word

def get_cart_id():
  set_address(rom_base_address)
  buffer = bytearray(64)
  for i in range(0, 64, 2):
    word = read_word()
    low_byte = word & 0xFF
    high_byte = word >> 8
    buffer[i] = high_byte
    buffer[i + 1] = low_byte
  return buffer

def detect_cart_size():
  """Detect cart size by checking for mirroring of ROM data"""
  print("Detecting cart size...")
  
  # Get the first 16 bytes as a reference
  set_address(rom_base_address)
  reference_data = bytearray(16)
  for i in range(0, 16, 2):
    word = read_word()
    reference_data[i] = word >> 8
    reference_data[i + 1] = word & 0xFF
  
  # Check for mirroring at different sizes (4MB, 8MB, 12MB, 16MB, 32MB, 64MB)
  sizes_to_check = [4, 8, 12, 16, 32, 64]
  detected_size = 64  # Default to maximum size if no mirroring detected
  
  for size in sizes_to_check:
    # Calculate address to check for mirroring
    mirror_address = rom_base_address + (size * 1024 * 1024)
    
    # Read data at potential mirror address
    set_address(mirror_address)
    mirror_match = True
    
    for i in range(0, 16, 2):
      word = read_word()
      high_byte = word >> 8
      low_byte = word & 0xFF
      
      # Compare with reference data
      if high_byte != reference_data[i] or low_byte != reference_data[i + 1]:
        mirror_match = False
        break
    
    # If we found a mirror, we know the cart size
    if mirror_match:
      detected_size = size
      break
  
  print(f"Detected cart size: {detected_size}MB")
  return detected_size

def stream_cart_data():
  """Stream cart data via USB UART"""
  # Get cart ID and name
  cart_id = get_cart_id()
  try:
    cart_name = cart_id[32:42].decode('utf-8').strip()
  except:
    cart_name = "UNKNOWN"
  print(f'Cart Name: {cart_name}')
  
  # Detect cart size
  cart_size = detect_cart_size()
  
  # Send cart info to host
  uart.write(f"CART_INFO:{cart_name},{cart_size}\n".encode())
  
  # Wait for host to be ready
  print("Waiting for host...")
  while True:
    if uart.any():
      cmd = uart.readline().decode().strip() # type: ignore
      if cmd == "START_DUMP":
        break
      sleep_ms(100)
  
  print("Dumping cart...")
  
  # Buffer for reading data
  buffer_size = 512
  buffer = bytearray(buffer_size)
  
  # Calculate total size in bytes
  total_size = cart_size * 1024 * 1024
  
  # Read and stream the data
  for rom_address in range(rom_base_address, rom_base_address + total_size, buffer_size):
    # Set the address for the next chunk
    set_address(rom_address)
    
    # Read data into buffer
    for i in range(0, buffer_size, 2):
      word = read_word()
      buffer[i] = word >> 8
      buffer[i + 1] = word & 0xFF
    
    # Send data over UART
    uart.write(buffer)
    
    # Report progress
    progress = ((rom_address - rom_base_address) / total_size) * 100
    if (rom_address & 0x3FFF) == 0:
      led_pin.high()
      print(f'Progress: {progress:.1f}%', end='\r')
    else:
      led_pin.low()
  
  print("\nDump completed!")
  uart.write(b"DUMP_COMPLETE\n")

def main():
  try:
    setup_cart()
    stream_cart_data()
  except Exception as e:
    print(f"Error: {e}")
    # Print exception details
    sys.print_exception(e) if hasattr(sys, 'print_exception') else print(f"Exception details: {e}")

if __name__ == "__main__":
  main()

