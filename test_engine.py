import unittest
from unittest.mock import patch, MagicMock
from server import MacroEngine

class TestMacroEngine(unittest.TestCase):
    @patch('server.ctypes.windll.user32.mouse_event')
    @patch('server.ctypes.windll.user32.SetCursorPos')
    def test_engine_click_to_end(self, mock_set_cursor, mock_mouse_event):
        engine = MacroEngine()
        script = {
            "step_1": {
                "type": "click",
                "x": 100,
                "y": 200,
                "delay": 0.1,
                "next": "end"
            }
        }
        engine.load_script(script)
        
        success = engine.start("step_1")
        self.assertTrue(success)
        
        # Wait for the thread to finish executing the script
        engine.thread.join(timeout=2.0)
        
        self.assertFalse(engine.is_running)
        self.assertIsNone(engine.current_step)
        
        # Verify the mocked calls were made
        mock_set_cursor.assert_called_with(100, 200)
        self.assertEqual(mock_mouse_event.call_count, 2)

if __name__ == '__main__':
    unittest.main()
