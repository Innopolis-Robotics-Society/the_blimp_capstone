import serial
import struct
import time


class NooploopConsoleParser:
    def __init__(self, port="/dev/ttyCH343USB0", baudrate=921600, telemetry_dict=None):
        self.ser = serial.Serial(port, baudrate, timeout=0.1)
        self.buffer = bytearray()
        self.anchor_frame_len = 896  # Default frame length

        # Store reference to shared telemetry dictionary (for web dashboard integration)
        self.telemetry = telemetry_dict if telemetry_dict is not None else {}

        # Timer to limit terminal output frequency (1 Hz)
        self.last_print_time = 0.0

    def calibrate(self):
        print("Calibration: determining exact Anchor_Frame0 packet length...")
        time.sleep(0.5)  # Let buffer fill up

        raw_data = bytearray()
        start_time = time.time()

        # Collect data for length analysis
        while len(raw_data) < 4000 and (time.time() - start_time) < 2.0:
            if self.ser.in_waiting > 0:
                raw_data.extend(self.ser.read(self.ser.in_waiting))

        # Find distance between two markers 55 00
        idx1 = raw_data.find(b'\x55\x00')
        if idx1 != -1:
            idx2 = raw_data.find(b'\x55\x00', idx1 + 2)
            if idx2 != -1:
                self.anchor_frame_len = idx2 - idx1
                print(f"[Success] Auto-detected packet length: {self.anchor_frame_len} bytes.")
                return

        print("[Warning] Failed to auto-detect length. Using default: 896 bytes.")

    def run(self):
        self.calibrate()
        print(f"Parser started on port {self.ser.port}...")
        try:
            while True:
                if self.ser.in_waiting > 0:
                    self.buffer.extend(self.ser.read(self.ser.in_waiting))
                    self.parse_buffer()
        except KeyboardInterrupt:
            print("\nParser stopped.")
        finally:
            self.ser.close()

    def parse_buffer(self):
        while len(self.buffer) >= 4:
            # Look for frame start marker 0x55
            if self.buffer[0] != 0x55:
                self.buffer.pop(0)
                continue

            # Check function byte
            func_mark = self.buffer[1]
            if func_mark not in (0x00, 0xfb):
                self.buffer.pop(0)
                continue

            # Set frame length depending on frame type
            if func_mark == 0x00:
                frame_len = self.anchor_frame_len
            else:  # 0xfb (Node_Frame3)
                frame_len = struct.unpack("<H", self.buffer[2:4])[0]

            # Wait until full packet is available
            if len(self.buffer) < frame_len:
                break

            # Extract packet and clear buffer
            packet = self.buffer[:frame_len]
            del self.buffer[:frame_len]

            # Validate frame integrity
            if func_mark == 0x00:
                # For Anchor_Frame0, end marker is fixed byte 0xee
                if packet[-1] != 0xee:
                    pass
            else:
                expected_checksum = packet[-1]
                calculated_checksum = sum(packet[:-1]) & 0xFF
                if expected_checksum != calculated_checksum:
                    continue

            # Parse coordinates from Anchor_Frame0 (0x00)
            if func_mark == 0x00:
                self.extract_coordinates_anchor_frame0(packet)

    def extract_coordinates_anchor_frame0(self, packet):
        frame_len = len(packet)
        offset = 2

        # Check if it's time to print to terminal (once per second)
        current_time = time.time()
        should_print = (current_time - self.last_print_time >= 1.0)

        # Data block section ends at byte 812
        while offset + 27 <= 812:
            block = packet[offset: offset + 27]
            tag_id = block[0]
            role = block[1]

            # Role 0x02 corresponds to TAG. ID 0xFF means empty slot.
            if tag_id != 0xFF and role == 0x02:
                # X, Y, Z coordinates (3 bytes each, signed int24)
                x_raw = int.from_bytes(block[2:5], byteorder='little', signed=True)
                y_raw = int.from_bytes(block[5:8], byteorder='little', signed=True)
                z_raw = int.from_bytes(block[8:11], byteorder='little', signed=True)

                # In NLink, invalid/uncomputed coordinate is -8388608 (0x800000)
                if x_raw != -8388608 and y_raw != -8388608:
                    pos_x = x_raw / 1000.0
                    pos_y = y_raw / 1000.0
                    pos_z = z_raw / 1000.0

                    # 1. Always update telemetry dictionary for smooth dashboard rendering
                    self.telemetry['x'] = pos_x
                    self.telemetry['y'] = pos_y
                    self.telemetry['z'] = pos_z

                    # 2. Print to console only once per second to avoid spam
                    if should_print:
                        print(
                            f"[Success] Tag ID: {tag_id} | "
                            f"X: {pos_x:+.3f} m | Y: {pos_y:+.3f} m | Z: {pos_z:+.3f} m"
                        )

            offset += 27

        if should_print:
            self.last_print_time = current_time


if __name__ == "__main__":
    parser = NooploopConsoleParser(port="/dev/ttyCH343USB0", baudrate=921600)
    parser.run()