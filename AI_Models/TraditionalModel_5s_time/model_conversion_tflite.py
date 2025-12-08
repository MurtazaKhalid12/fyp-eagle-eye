import re
import os

# --- CONFIGURATION ---
# Make sure this filename matches exactly what you created
input_text_file = "person_detect_model_data.h" 
output_model_file = "my_esp32_model.tflite"
# ---------------------

def main():
    # Check if the input file actually exists before trying to read it
    if not os.path.exists(input_text_file):
        print(f"❌ Error: Could not find '{input_text_file}'.")
        print("   -> Please open your .h file, copy ONLY the hex numbers (inside { }),")
        print(f"   -> and paste them into a new file named '{input_text_file}'.")
        return

    try:
        print(f"Reading {input_text_file}...")
        with open(input_text_file, "r") as f:
            hex_string = f.read()

        # Regex to find hex values like 0x00, 0xAB, etc.
        print("Extracting hex values...")
        hex_values = re.findall(r'0x([0-9a-fA-F]+)', hex_string)

        if not hex_values:
            print("❌ Error: No hex values found!")
            print("   -> Ensure your text file contains data looking like: 0x01, 0xA2, 0xFF")
            return

        # Convert to binary byte array
        print(f"Converting {len(hex_values)} bytes...")
        byte_data = bytearray([int(x, 16) for x in hex_values])

        # Save as .tflite
        with open(output_model_file, "wb") as f:
            f.write(byte_data)

        print(f"✅ Success! Model saved as '{output_model_file}'")
        print(f"   -> File size: {len(byte_data) / 1024:.2f} KB")

    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()