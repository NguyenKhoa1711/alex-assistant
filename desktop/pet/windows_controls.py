"""Native controls. Imported only in the short-lived device action worker.

Windows SDK interfaces: endpointvolume.h / mmdeviceapi.h.
Brightness: https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmimonitorbrightnessmethods
"""
from ctypes import POINTER, c_float, c_int, c_void_p
from ctypes.wintypes import BOOL, DWORD, UINT
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown, CoCreateInstance, CLSCTX_INPROC_SERVER


class IMMDevice(IUnknown):
    _iid_ = GUID('{D666063F-1587-4E43-81F1-B948E807363F}')
    _methods_ = [COMMETHOD([], HRESULT, 'Activate',
                          (['in'], POINTER(GUID), 'iid'), (['in'], DWORD, 'context'),
                          (['in'], c_void_p, 'params'), (['out'], POINTER(POINTER(IUnknown)), 'interface'))]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID('{A95664D2-9614-4F35-A746-DE8DB63617E6}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'EnumAudioEndpoints', (['in'], c_int, 'flow'),
                  (['in'], DWORD, 'mask'), (['out'], POINTER(c_void_p), 'devices')),
        COMMETHOD([], HRESULT, 'GetDefaultAudioEndpoint', (['in'], c_int, 'flow'),
                  (['in'], c_int, 'role'), (['out'], POINTER(POINTER(IMMDevice)), 'device'))]


class IAudioEndpointVolume(IUnknown):
    _iid_ = GUID('{5CDF2C82-841E-4546-9722-0CF74078229A}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'RegisterControlChangeNotify', (['in'], c_void_p, 'notify')),
        COMMETHOD([], HRESULT, 'UnregisterControlChangeNotify', (['in'], c_void_p, 'notify')),
        COMMETHOD([], HRESULT, 'GetChannelCount', (['out'], POINTER(UINT), 'count')),
        COMMETHOD([], HRESULT, 'SetMasterVolumeLevel', (['in'], c_float, 'db'), (['in'], POINTER(GUID), 'event')),
        COMMETHOD([], HRESULT, 'SetMasterVolumeLevelScalar', (['in'], c_float, 'level'), (['in'], POINTER(GUID), 'event')),
        COMMETHOD([], HRESULT, 'GetMasterVolumeLevel', (['out'], POINTER(c_float), 'db')),
        COMMETHOD([], HRESULT, 'GetMasterVolumeLevelScalar', (['out'], POINTER(c_float), 'level')),
        COMMETHOD([], HRESULT, 'SetChannelVolumeLevel', (['in'], UINT, 'channel'), (['in'], c_float, 'db'), (['in'], POINTER(GUID), 'event')),
        COMMETHOD([], HRESULT, 'SetChannelVolumeLevelScalar', (['in'], UINT, 'channel'), (['in'], c_float, 'level'), (['in'], POINTER(GUID), 'event')),
        COMMETHOD([], HRESULT, 'GetChannelVolumeLevel', (['in'], UINT, 'channel'), (['out'], POINTER(c_float), 'db')),
        COMMETHOD([], HRESULT, 'GetChannelVolumeLevelScalar', (['in'], UINT, 'channel'), (['out'], POINTER(c_float), 'level')),
        COMMETHOD([], HRESULT, 'SetMute', (['in'], BOOL, 'muted'), (['in'], POINTER(GUID), 'event')),
        COMMETHOD([], HRESULT, 'GetMute', (['out'], POINTER(BOOL), 'muted'))]


class WindowsVolume:
    def __init__(self):
        self.enumerator = CoCreateInstance(GUID('{BCDE0395-E52F-467C-8E3D-C4579291692E}'),
                                           interface=IMMDeviceEnumerator, clsctx=CLSCTX_INPROC_SERVER)
        # eRender + eMultimedia: the current playback device, never the microphone.
        self.device = self.enumerator.GetDefaultAudioEndpoint(0, 1)
        self.volume = self.device.Activate(IAudioEndpointVolume._iid_, CLSCTX_INPROC_SERVER, None).QueryInterface(IAudioEndpointVolume)

    def current(self):
        return {'level': round(self.volume.GetMasterVolumeLevelScalar()*100),
                'muted': bool(self.volume.GetMute())}

    def supported_level(self, level): return int(level)
    def set_level(self, level): self.volume.SetMasterVolumeLevelScalar(level/100, None)
    def set_muted(self, muted): self.volume.SetMute(bool(muted), None)


class WindowsBrightness:
    def __init__(self):
        from win32com.client import Dispatch
        self.service = Dispatch('WbemScripting.SWbemLocator').ConnectServer('.', r'root\WMI')
        panels = list(self.service.ExecQuery('SELECT * FROM WmiMonitorBrightness WHERE Active=True'))
        if len(panels) != 1:
            raise RuntimeError('Windows chưa cung cấp một màn hình laptop duy nhất để chỉnh độ sáng.')
        panel = panels[0]
        self.instance = panel.Properties_('InstanceName').Value
        self.levels = sorted({int(v) for v in panel.Properties_('Level').Value if 0 <= int(v) <= 100})
        if not self.levels:
            raise RuntimeError('Màn hình chưa cung cấp các mức sáng được hỗ trợ.')
        methods = [m for m in self.service.ExecQuery('SELECT * FROM WmiMonitorBrightnessMethods WHERE Active=True')
                   if m.Properties_('InstanceName').Value == self.instance]
        if len(methods) != 1:
            raise RuntimeError('Chưa tìm được bộ điều khiển độ sáng của màn hình laptop.')
        self.methods = methods[0]

    def current(self):
        panels = [p for p in self.service.ExecQuery('SELECT * FROM WmiMonitorBrightness WHERE Active=True')
                  if p.Properties_('InstanceName').Value == self.instance]
        if len(panels) != 1:
            raise RuntimeError('Màn hình đã thay đổi; mình dừng chỉnh độ sáng.')
        return {'level': int(panels[0].Properties_('CurrentBrightness').Value)}

    def supported_level(self, level): return min(self.levels, key=lambda value: abs(value-level))

    def set_level(self, level):
        params = self.methods.Methods_('WmiSetBrightness').InParameters.SpawnInstance_()
        params.Properties_('Timeout').Value = 0
        params.Properties_('Brightness').Value = int(level)
        output = self.methods.ExecMethod_('WmiSetBrightness', params)
        # This laptop's WMI driver exposes no output object. The caller still
        # verifies CurrentBrightness before reporting success.
        if output is not None and int(output.Properties_('ReturnValue').Value) != 0:
            raise RuntimeError('Windows chưa áp dụng được độ sáng màn hình.')
