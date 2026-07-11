import unittest
from unittest.mock import patch
import datetime
from main import BotLogic

class TestScheduler(unittest.TestCase):
    def setUp(self):
        # Mock callbacks needed for BotLogic init
        self.log_callback = lambda msg: None
        self.get_coordinates = lambda: []
        self.get_delay = lambda: 1.0
        self.get_loops = lambda: 0
        self.get_stop_region = lambda: None
        self.get_tolerance = lambda: 5.0
        self.get_check_delay = lambda: 0.5
        
        self.rules = []
        self.enabled = True
        
        self.bot = BotLogic(
            self.log_callback,
            self.get_coordinates,
            self.get_delay,
            self.get_loops,
            self.get_stop_region,
            self.get_tolerance,
            self.get_check_delay,
            lambda: self.rules,
            lambda: self.enabled
        )

    @patch('main.datetime')
    def test_odd_hour_active(self, mock_datetime):
        # Set time to 13:10 (Odd hour, minute 10)
        mock_now = datetime.datetime(2026, 7, 12, 13, 10, 0)
        mock_datetime.datetime.now.return_value = mock_now
        
        self.rules = [{'type': 'Odd', 'start': 5, 'end': 15}]
        self.assertTrue(self.bot._is_scheduled_time_active(), "Should be active during odd hour matching window.")

    @patch('main.datetime')
    def test_odd_hour_inactive(self, mock_datetime):
        # Set time to 13:20 (Odd hour, minute 20) - outside window
        mock_now = datetime.datetime(2026, 7, 12, 13, 20, 0)
        mock_datetime.datetime.now.return_value = mock_now
        
        self.rules = [{'type': 'Odd', 'start': 5, 'end': 15}]
        self.assertFalse(self.bot._is_scheduled_time_active(), "Should be inactive when minute is outside window.")

    @patch('main.datetime')
    def test_even_hour_active(self, mock_datetime):
        # Set time to 14:30 (Even hour, minute 30)
        mock_now = datetime.datetime(2026, 7, 12, 14, 30, 0)
        mock_datetime.datetime.now.return_value = mock_now
        
        self.rules = [{'type': 'Even', 'start': 30, 'end': 45}]
        self.assertTrue(self.bot._is_scheduled_time_active(), "Should be active during even hour matching window.")

    @patch('main.datetime')
    def test_even_hour_wrong_parity(self, mock_datetime):
        # Set time to 15:30 (Odd hour, minute 30)
        mock_now = datetime.datetime(2026, 7, 12, 15, 30, 0)
        mock_datetime.datetime.now.return_value = mock_now
        
        self.rules = [{'type': 'Even', 'start': 30, 'end': 45}]
        self.assertFalse(self.bot._is_scheduled_time_active(), "Should be inactive during odd hour when rule is Even.")

    @patch('main.datetime')
    def test_disabled_schedule_returns_true(self, mock_datetime):
        # When schedule is disabled, it should always return True (allow clicking)
        self.enabled = False
        self.rules = [{'type': 'Even', 'start': 30, 'end': 45}]
        self.assertTrue(self.bot._is_scheduled_time_active(), "Should return True when scheduler is disabled.")

if __name__ == '__main__':
    unittest.main()
