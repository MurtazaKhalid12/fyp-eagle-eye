import os
import shutil
from pathlib import Path

source_dir = Path(r"C:\fyp-eagle-eye\sketchboard\human")
humans_dest = Path(r"C:\fyp-eagle-eye\sketchboard\dataset\Humans")
nonhumans_dest = Path(r"C:\fyp-eagle-eye\sketchboard\dataset\NonHuman")

DUPLICATIONS = 5 # Copy each image 5 times

copied_h = 0
copied_n = 0

for file in source_dir.glob("*.jpg"):
    is_nonhuman = "nonhuman" in file.name.lower()
    dest_dir = nonhumans_dest if is_nonhuman else humans_dest
    
    for i in range(DUPLICATIONS):
        new_name = f"esp32_injected_v{i}_{file.name}"
        dest_path = dest_dir / new_name
        shutil.copy2(file, dest_path)
        
        if is_nonhuman: copied_n += 1
        else: copied_h += 1

print(f"Injected {copied_h} Humans and {copied_n} NonHumans into the training dataset.")
