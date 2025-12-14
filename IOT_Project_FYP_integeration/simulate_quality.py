import os
from PIL import Image
import glob

# 1. Find latest image
list_of_files = glob.glob('captures/*.jpg') 
if not list_of_files:
    print("No images found in captures/ folder!")
    exit()

latest_file = max(list_of_files, key=os.path.getctime)
print(f"Using original image: {latest_file}")

img = Image.open(latest_file)
original_size = img.size
print(f"Original Size: {original_size}")

# 2. Define resolutions to simulate
resolutions = [
    (96, 96, "AI_Input_Buffer"),      # Option 3 (Fastest)
    (160, 120, "QQVGA_Low_Quality"),  # Option 2 (Medium)
    (320, 240, "QVGA_Standard")       # Current (Slow)
]

# 3. Generate and Save
for w, h, label in resolutions:
    # Resize
    low_res = img.resize((w, h), Image.Resampling.NEAREST)
    
    # Save
    filename = f"captures/DEMO_{label}_{w}x{h}.jpg"
    low_res.save(filename)
    print(f"Created: {filename}")

print("\nDone! Check the 'captures' folder to compare quality.")
