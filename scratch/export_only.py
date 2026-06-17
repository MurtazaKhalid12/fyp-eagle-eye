import os
import time
import win32com.client

def export_all_slides_to_png():
    print("Initializing PowerPoint COM client...")
    import pythoncom
    pythoncom.CoInitialize()
    
    powerpoint = win32com.client.Dispatch("PowerPoint.Application")
    time.sleep(2)  # Give PowerPoint time to fully initialize
    
    ppt_path = "C:\\fyp-eagle-eye\\esp32_architecture.pptx"
    abs_ppt_path = os.path.abspath(ppt_path)
    
    ppt = None
    try:
        print(f"Opening presentation: {abs_ppt_path}")
        for attempt in range(5):
            try:
                ppt = powerpoint.Presentations.Open(abs_ppt_path, ReadOnly=True, WithWindow=False)
                break
            except Exception as ex:
                print(f"Attempt {attempt+1} failed to open presentation: {ex}")
                time.sleep(1)
        
        if ppt is None:
            raise Exception("Could not open presentation after several attempts.")
            
        # Define slides to export
        slide_mappings = {
            1: "C:\\fyp-eagle-eye\\esp32_lit_review_preview.png",
            2: "C:\\fyp-eagle-eye\\esp32_foundations_preview.png",
            3: "C:\\fyp-eagle-eye\\esp32_architecture_ppt_preview.png",
            4: "C:\\fyp-eagle-eye\\esp32_model_speed_preview.png"
        }
        
        for num, path in slide_mappings.items():
            print(f"Exporting Slide {num} to {path}...")
            ppt.Slides[num].Export(path, "PNG")
            
        ppt.Close()
        print("All slides exported successfully!")
    except Exception as e:
        print("Error during slide export:", e)
    finally:
        try:
            powerpoint.Quit()
        except Exception as qe:
            print("Could not call Quit on PowerPoint application:", qe)
        pythoncom.CoUninitialize()

if __name__ == "__main__":
    export_all_slides_to_png()
