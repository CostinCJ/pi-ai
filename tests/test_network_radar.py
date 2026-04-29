from unittest.mock import patch, MagicMock
import network_radar


def _mock_run(stdout):
    result = MagicMock()
    result.stdout = stdout
    result.returncode = 0
    return result


def test_phone_is_home_true():
    with patch("network_radar.PHONE_MAC", "aa:bb:cc:dd:ee:ff"), \
         patch("network_radar.subprocess.run", return_value=_mock_run(
             "192.168.1.10\taa:bb:cc:dd:ee:ff\tApple, Inc.\n"
         )):
        assert network_radar.phone_is_home() is True


def test_phone_is_home_false():
    with patch("network_radar.PHONE_MAC", "aa:bb:cc:dd:ee:ff"), \
         patch("network_radar.subprocess.run", return_value=_mock_run(
             "192.168.1.1\t11:22:33:44:55:66\tTP-Link\n"
         )):
        assert network_radar.phone_is_home() is False


def test_phone_is_home_none_on_exception():
    with patch("network_radar.subprocess.run", side_effect=Exception("not found")):
        assert network_radar.phone_is_home() is None


def test_phone_is_home_none_on_scan_failure():
    result = _mock_run("")
    result.returncode = 1
    with patch("network_radar.subprocess.run", return_value=result):
        assert network_radar.phone_is_home() is None


def test_phone_is_home_case_insensitive():
    with patch("network_radar.PHONE_MAC", "AA:BB:CC:DD:EE:FF"), \
         patch("network_radar.subprocess.run", return_value=_mock_run(
             "192.168.1.10\taa:bb:cc:dd:ee:ff\tApple\n"
         )):
        assert network_radar.phone_is_home() is True
