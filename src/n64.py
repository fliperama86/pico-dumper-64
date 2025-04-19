import uasyncio
import sys
from machine import Pin
from utime import sleep_us
import os
import time
import rp2 # Added RP2 import

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

# --- PIO Program - Explicit Delay Separation ---
@rp2.asm_pio(
    sideset_init=rp2.PIO.OUT_HIGH, # read_pin starts high (inactive low)
    in_shiftdir=rp2.PIO.SHIFT_LEFT,
    push_thresh=16
)
def read_word_pio():
    pull(block)             # Wait for trigger
    mov(x, osr)             # Discard trigger value

    # Set side 0 (RD low). Takes effect after this instruction completes (1 cycle).
    nop()         .side(0)

    # Explicit delay after RD has gone low (~25 cycles for N64 data setup).
    nop() [4] # 5 cycles
    nop() [4] # 5 cycles
    nop() [4] # 5 cycles
    nop() [4] # 5 cycles
    nop() [4] # 5 cycles

    # Sample data (RD has been low for ~26 cycles)
    in_(pins, 16)

    # Push data
    push()                       # Push ISR -> RX FIFO

    # Set side 1 (RD high). Takes effect after this instruction completes (1 cycle).
    nop()         .side(1)

    # Loop controlled by pull(block)


# Global state machine instance
sm_read = None

def initialize_read_pio():
    global sm_read
    # Define the 16 data input pins for PIO (uses pico_pins_map)
    data_base_pin = Pin(pico_pins_map[0]) # Base pin for the 'in' group

    # The PIO program needs exclusive control of the read_pin
    read_pin_pio = Pin(19) # Match the original read_pin number

    # Check if SM is already active (useful for debugging/re-running)
    if sm_read and sm_read.active():
        sm_read.active(0)

    sm_read = rp2.StateMachine(
        0,                      # State machine ID 0
        read_word_pio,          # The PIO program
        freq=125_000_000,       # Clock frequency (adjust if overclocking)
        sideset_base=read_pin_pio, # The pin controlled by sideset
        in_base=data_base_pin,  # Base pin for the 'in' instruction
    )
    # Ensure data pins are configured as inputs *before* activating SM
    # (set_address already does this before read_word is called, but good practice)
    set_pico_address_pins_in()
    sm_read.active(1)

def setup_cart():
  # Set Address Pins to Output initially
  set_pico_address_pins_out()

  # Set Control Pins (excluding read_pin) to Output
  # RESET(16), WR(20), aleL(27), aleH(26)
  for pin_num in [16, 20, 27, 26]:
      Pin(pin_num).init(Pin.OUT)

  reset_pin = Pin(16)
  write_pin = Pin(20)
  ale_low_pin = Pin(27)
  ale_high_pin = Pin(26)

  # Output a high signal on WR(PH5), pins are active low
  write_pin.high()
  # read_pin.high() # PIO now controls read_pin initial state via sideset_init

  # Pull aleL(PC0) low and aleH(PC1) high
  ale_low_pin.low()
  ale_high_pin.high()

  # Wait until all is stable
  sleep_us(1)

  # Pull RESET(PH0) high to start cart
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
  # Ensure address pins are inputs (set_address should leave them as inputs)
  # set_pico_address_pins_in() # This check might be redundant if set_address is reliable

  # Debug print to check sm_read before use
  if sm_read is None:
      # This check should ideally not be needed anymore, but keep for safety?
      print("ERROR: sm_read is None in read_word!", file=sys.stderr)
      raise RuntimeError("PIO State Machine not initialized")

  sm_read.put(0)      # Trigger the PIO state machine
  word = sm_read.get() # Read the 16-bit word from RX FIFO (blocking)
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
                                return size_mb
                            except ValueError:
                                pass # Add pass if needed, although returning 0 below handles this case

                except Exception as e:
                    # Decide whether to break or try to continue
                    break # Safer to stop if the format is unexpected

    except OSError as e:
        if e.errno == 2: # ENOENT
            pass # Added pass for empty block
        else:
            pass # Added pass for empty block

    return 0 # Return 0 if not found or error occurred

async def read_cart():
  # Remove file handling and buffer logic
  # buffer_size = 100 * 1024
  writer = uasyncio.StreamWriter(sys.stdout.buffer, {}) # Use stdout.buffer for binary stream

  # Calculate total size based on global cart_size
  total_bytes = cart_size * 1024 * 1024
  end_address = rom_base_address + total_bytes

  # Read the data in 512 byte chunks
  for rom_address in range(rom_base_address, end_address, 512):
      # Set the address for the next 512 bytes
      set_address(rom_address)

      # Create a buffer for this chunk
      chunk_buffer = bytearray(512)

      for bufferIndex in range(0, 512, 2):
          word = read_word() # Calls the PIO version

          # Note: Order is high byte first for N64 ROMs
          chunk_buffer[bufferIndex] = word >> 8
          chunk_buffer[bufferIndex + 1] = word & 0xFF

      # Write chunk to USB output asynchronously
      writer.write(chunk_buffer)
      await writer.drain() # Ensure data is flushed

      # Report progress via LED, removed stdout progress print
      if (rom_address & 0x3FFF) == 0:
        led_pin.high()
      else:
        led_pin.low()
  
  led_pin.low()

async def main():
    time.sleep(10) # User added this

    global cart_size # Declare intent to modify global variable

    initialize_read_pio() # <<< Initialize the PIO state machine here

    setup_cart()

    cart_header, checksum = get_cart_id()

    cart_name_bytes = cart_header[32:52] # Read up to 20 bytes for name
    # Clean up potential padding/garbage in name
    try:
        cart_name = cart_name_bytes.decode('utf-8').rstrip('\x00').strip()
    except Exception: # Changed from UnicodeDecodeError to generic Exception
        cart_name = "Invalid Name Encoding"

    # Attempt to get size from DB
    db_size = get_cart_size_from_db(checksum)
    if db_size > 0:
        cart_size = db_size
    else:
        # Keep the default cart_size = 12 defined globally
        pass # Add pass to fix indentation error

    await read_cart() # Call async function

# Run the async main function
uasyncio.run(main())

