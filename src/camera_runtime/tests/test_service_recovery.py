"""Reattach a known body's existing service endpoint without re-authentication."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import transport


class ServiceRecoveryTests(unittest.TestCase):
    def setUp(self):
        # Protocol tests own a fake device, including the new Linux host lease.
        self.host = patch('linux_host.CameraHost', return_value=MagicMock())
        self.host.start(); self.addCleanup(self.host.stop)

    def test_existing_session_is_read_before_any_authentication(self):
        expected = {'model': 'ILCE-7CM2', 'serial_sha256': 'body'}
        auth = Mock(driver=Mock())
        camera = Mock()
        with patch.object(transport, 'get_device', return_value=Mock()) as device, \
             patch.object(transport, 'Bounded', return_value=Mock()), \
             patch.object(transport, 'GenericUsbDriver'), \
             patch.object(transport, 'SonySenserAuthDevice', return_value=auth), \
             patch.object(transport, 'SonySenserDevice'), \
             patch.object(transport, 'SonySenserCamera', return_value=camera), \
             patch.object(transport, 'service_identity', return_value=expected), \
             patch.object(transport.usb.util, 'dispose_resources'):
            session = transport.RecoverySession(expected).__enter__()
            device.assert_called_once_with(0x0336)
            camera.getBackupPresetData.assert_called_once_with(True)
            auth.start.assert_not_called(); auth.authenticate.assert_not_called(); auth.stop.assert_not_called()
            session.healthy = False
            session.__exit__()
            auth.stop.assert_not_called()

    def test_wrong_body_or_timeout_never_stops_or_reauthenticates(self):
        for error in (False, True):
            expected = {'model': 'ILCE-7CM2', 'serial_sha256': 'owner'}
            auth, camera = Mock(driver=Mock()), Mock()
            if error: camera.getBackupPresetData.side_effect = TimeoutError('unknown')
            with patch.object(transport, 'get_device', return_value=Mock()), \
                 patch.object(transport, 'Bounded', return_value=Mock()), \
                 patch.object(transport, 'GenericUsbDriver'), \
                 patch.object(transport, 'SonySenserAuthDevice', return_value=auth), \
                 patch.object(transport, 'SonySenserDevice'), \
                 patch.object(transport, 'SonySenserCamera', return_value=camera), \
                 patch.object(transport, 'service_identity', return_value=dict(expected, serial_sha256='other')), \
                 patch.object(transport.usb.util, 'dispose_resources'):
                with self.assertRaises((ValueError, TimeoutError)):
                    transport.RecoverySession(expected).__enter__()
                auth.start.assert_not_called(); auth.authenticate.assert_not_called(); auth.stop.assert_not_called()

    def test_unrecorded_body_cannot_use_service_reattachment(self):
        for identity in (None, {}, {'model': 'ILCE-7CM2'}, {'model': 'ILCE-7M4', 'serial_sha256': 'body'}):
            with patch.object(transport, 'get_device') as device, self.assertRaises(ValueError):
                transport.RecoverySession(identity).__enter__()
            device.assert_not_called()
