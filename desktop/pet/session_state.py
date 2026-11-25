"""Read local Windows session state; no credential or network operations."""
def _pc_unlocked() -> bool:
    """Fail closed if this process cannot verify the input desktop."""
    if __import__('os').name != 'nt':
        return True
    import ctypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.OpenInputDesktop.restype = ctypes.c_void_p
    user.OpenInputDesktop.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    user.GetUserObjectInformationW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
    user.CloseDesktop.argtypes = [ctypes.c_void_p]
    desktop = user.OpenInputDesktop(0, False, 1)
    if not desktop:
        return False
    try:
        buffer = ctypes.create_unicode_buffer(128)
        needed = ctypes.c_ulong()
        if not user.GetUserObjectInformationW(desktop, 2, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)):
            return False
        return buffer.value == 'Default'
    finally:
        user.CloseDesktop(desktop)
