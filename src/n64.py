from machine import Pin
from utime import sleep_us
import os

cart_size = 12
rom_base_address = 0x10000000
file_path = "dump.n64"
led_pin = Pin("LED", Pin.OUT)

pico_pins_map = [0, 1, 2, 3, 4, 5, 6, 7, 15, 14, 13, 12, 11, 10, 9, 8]
address_pins = [Pin(i, Pin.OUT) for i in pico_pins_map]

write_pin = Pin(20, Pin.OUT)
read_pin = Pin(19, Pin.OUT)

ale_low_pin = Pin(27, Pin.OUT)
ale_high_pin = Pin(26, Pin.OUT)

reset_pin = Pin(16, Pin.OUT)

def setup_cart():
  # Set Address Pins to Output and set them low
  set_pico_address_pins_out()
  
  # Set Control Pins to Output RESET(PH0) WR(PH5) RD(PH6) aleL(PC0) aleH(PC1)
  for pin in [reset_pin, write_pin, read_pin, ale_low_pin, ale_high_pin]:
    pin.init(Pin.OUT)

  # Pull RESET(PH0) low until we are ready
  
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

def print_hex(data):
  for i in range(0, len(data), 16):
    line = data[i:i+16]
    hex_line = ' '.join(f'{byte:02X}' for byte in line)
    print(hex_line)

def get_cart_id():
  """Reads the first 64 bytes of the cartridge header."""
  set_address(rom_base_address)
  buffer = bytearray(64)
  for i in range(0, 64, 2):
    word = read_word()
    low_byte = word & 0xFF
    high_byte = word >> 8
    buffer[i] = high_byte
    buffer[i + 1] = low_byte

  # Extract CRC1 checksum (bytes 0x10-0x13) and format as hex string
  checksum_bytes = buffer[0x10:0x14]
  checksum_str = ''.join(f'{b:02X}' for b in checksum_bytes)

  return buffer, checksum_str

# n64.txt should be placed in the root directory of the Pico's filesystem.
# Expected format (repeat for each entry):
# <ROM Name>
# <Checksum>,<Size>,<SaveType>
# <Empty Line>
# Example:
# THE LEGEND OF ZELDA
# EDE79053,32,5
#
N64_DB_PATH = "n64.txt"

def get_cart_size_from_db(checksum_str):
    """Looks up the cart size in the n64.txt database using the checksum."""
    try:
        with open(N64_DB_PATH, 'r') as db_file:
            while True:
                try:
                    # Skip name line
                    name_line = db_file.readline()
                    if not name_line: break # End of file

                    # Read info line (Checksum,Size,SaveType)
                    info_line = db_file.readline()
                    if not info_line: break # Unexpected end of file

                    # Skip empty line
                    empty_line = db_file.readline()
                    # Allow for EOF after empty line
                    # if not empty_line: break

                    parts = info_line.strip().split(',')
                    if len(parts) >= 2:
                        db_checksum = parts[0]
                        if db_checksum == checksum_str:
                            try:
                                size_mb = int(parts[1])
                                print(f"Found cart size in DB: {size_mb} MB")
                                return size_mb
                            except ValueError:
                                print(f"Warning: Invalid size format in DB for checksum {checksum_str}")
                                # Continue searching in case of multiple entries? Or return 0?
                                # Let's return 0 for this entry and continue searching for safety.

                except Exception as e:
                    print(f"Error processing line in {N64_DB_PATH}: {e}")
                    # Decide whether to break or try to continue
                    break # Safer to stop if the format is unexpected

    except OSError as e:
        if e.errno == 2: # ENOENT
            print(f"Warning: Database file '{N64_DB_PATH}' not found.")
        else:
            print(f"Error opening database file '{N64_DB_PATH}': {e}")

    print("Cart size not found in DB.")
    return 0 # Return 0 if not found or error occurred

max_file_size = 1024 * 1024
def read_cart():
  buffer_size = 100 * 1024
  # Try to remove the old file, but ignore error if it doesn't exist
  try:
    os.remove(file_path)
  except OSError as e:
    if e.errno != 2: # errno 2 is ENOENT (No such file or directory)
        raise # Re-raise unexpected errors
  
  with open(file_path, 'wb') as file:
    write_buffer = bytearray(buffer_size)
    offset = 0
    progress = 0

    # Read the data in 512 byte chunks
    for rom_address in range(rom_base_address, rom_base_address + (cart_size * 1024 * 1024), 512):
      # Set the address for the next 512 bytes
      set_address(rom_address)

      for bufferIndex in range(0, 512, 2):
        word = read_word()
        write_buffer[bufferIndex + offset] = word >> 8
        write_buffer[bufferIndex + offset + 1] = word & 0xFF
      
      offset += 512
      
      if (offset >= buffer_size):
        file.write(write_buffer)
        offset = 0
      
      # Report progress
      if (rom_address & 0x3FFF) == 0:
        led_pin.high()
        print(f'Progress: {progress:.0f}%', end='\r')
        progress += (0x3FFF / max_file_size) * 100
      else:
        led_pin.low()
    
      if (file.tell() >= max_file_size):
        print('')
        print("Done!                                    ")
        break

def main():
  global cart_size # Declare intent to modify global variable

  setup_cart()
  cart_header, checksum = get_cart_id()
  cart_name_bytes = cart_header[32:52] # Read up to 20 bytes for name
  # Clean up potential padding/garbage in name
  try:
      cart_name = cart_name_bytes.decode('utf-8').rstrip('\x00').strip()
  except UnicodeDecodeError:
      cart_name = "Invalid Name Encoding"

  print('Cart Name:', cart_name)
  print('Checksum:', checksum)

  # Attempt to get size from DB
  db_size = get_cart_size_from_db(checksum)
  if db_size > 0:
      cart_size = db_size
      # Update max_file_size based on detected cart size
      global max_file_size
      max_file_size = cart_size * 1024 * 1024
  else:
      print(f"Using default cart size: {cart_size} MB")
      # Keep the default cart_size = 12 defined globally
      # Update max_file_size based on default cart size
      global max_file_size
      max_file_size = cart_size * 1024 * 1024

  print('Dumping cart...')
  setup_cart() # Re-setup in case DB reading took time? Or is it needed? Let's keep it for now.
  read_cart()
  
main()

