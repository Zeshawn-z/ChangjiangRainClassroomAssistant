import os
import time
import json
import threading

class PacketRecorder:
    def __init__(self, lesson_name, lesson_id):
        self.enabled = True
        self.lesson_name = lesson_name
        self.lesson_id = str(lesson_id)
        
        # Create logs directory in the current working directory
        self.log_dir = os.path.join(os.getcwd(), "logs")
        if not os.path.exists(self.log_dir):
            try:
                os.makedirs(self.log_dir)
            except Exception as e:
                print(f"Failed to create log directory: {e}")
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        # Sanitize filename
        safe_name = "".join([c for c in lesson_name if c.isalnum() or c in (' ', '-', '_')]).strip()
        self.filename = f"{safe_name}_{self.lesson_id}_{timestamp}.jsonl"
        self.filepath = os.path.join(self.log_dir, self.filename)
        self._write_lock = threading.Lock()
        
        self.record("session_start", {"lesson_name": lesson_name, "lesson_id": lesson_id}, "Session recording started")

    def record(self, event_type, payload, description=""):
        if not self.enabled:
            return
            
        entry = {
            "timestamp": time.time(),
            "readable_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event": event_type,
            "description": description,
            "payload": payload
        }
        
        # Use a thread to avoid blocking the main logic (especially network/UI threads)
        threading.Thread(target=self._write, args=(entry,)).start()

    def _write(self, entry):
        with self._write_lock:
            try:
                with open(self.filepath, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"DevTools Logging failed: {e}")

    def close(self):
        self.record("session_end", {}, "Session recording ended")
